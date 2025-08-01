from django.conf import settings
from django.utils.translation import gettext_lazy as _lazy
from zenpy import Zenpy
from zenpy.lib.api_objects import Identity as ZendeskIdentity
from zenpy.lib.api_objects import Ticket
from zenpy.lib.api_objects import User as ZendeskUser

NO_RESPONSE = _lazy("No response provided.")
LOGINLESS_TAG = "loginless_ticket"


class ZendeskClient:
    """Client to connect to Zendesk API."""

    def __init__(self, **kwargs):
        """Initialize Zendesk API client."""
        creds = {
            "email": settings.ZENDESK_USER_EMAIL,
            "token": settings.ZENDESK_API_TOKEN,
            "subdomain": settings.ZENDESK_SUBDOMAIN,
        }
        self.client = Zenpy(**creds)

    def _user_to_zendesk_user(self, user, email):
        """Given a Django user, return a Zendesk user."""
        # Four possible cases to account for:
        # 1. No Django User, No ZD User -> Create ZD User From Email
        # 2. No Django User, ZD User -> Get Existing ZD User Using Email
        # 3. Django User, No ZD User -> Create ZD User from Django User
        # 4. Django User, ZD User -> Get ZD User, Update Django User with Zendesk ID
        if not user.is_authenticated:
            # If the user already exists in Zendesk return
            # the Zendesk user object
            # instead of creating a new one
            if zuser := self.get_user_by_email(email):
                # No Django user, but yes ZD user
                return zuser
            # No Django user, no ZD user
            name = "Anonymous User"
            locale = "en-US"
            id = None
            external_id = None
            user_fields = None
        # Yes Django user
        else:
            fxa_uid = user.profile.fxa_uid
            id_str = user.profile.zendesk_id
            id = int(id_str) if id_str else None  # Yes Or No ZD User
            name = user.profile.display_name
            locale = user.profile.locale
            user_fields = {"user_id": fxa_uid}
            external_id = fxa_uid
        return ZendeskUser(
            id=id,
            verified=True,
            email=email or user.email,
            name=name,
            locale=locale,
            user_fields=user_fields,
            external_id=external_id,
        )

    def get_user_by_email(self, email):
        """Given an email, return a user from Zendesk."""
        # This returns a generator, but we only want/expect one user
        # If it returns more than one, we should fail
        # Otherwise return the Zendesk user object
        search_results = self.client.search(type="user", query=f"email:{email}")

        user_found = None
        for user in search_results:
            if user_found is not None:
                raise ValueError(f"Found more than one user with email {email}")
            user_found = user

        return user_found

    def create_user(self, user, email=""):
        """Given a Django user, create a user in Zendesk."""
        zendesk_user = self._user_to_zendesk_user(user, email=email)
        # call create_or_update to avoid duplicating users FxA previously created
        zendesk_user = self.client.users.create_or_update(zendesk_user)

        # We can't save anything to AnonymousUser Profile
        # as it has none
        if user.is_authenticated:
            user.profile.zendesk_id = str(zendesk_user.id)
            user.profile.save(update_fields=["zendesk_id"])

        return zendesk_user

    def update_user(self, user):
        """Given a Django user, update a user in Zendesk."""
        zendesk_user = self._user_to_zendesk_user(user, email=user.email)
        zendesk_user = self.client.users.update(zendesk_user)
        return zendesk_user

    def get_primary_email_identity(self, zendesk_user_id):
        """Fetch the identity with the primary email from Zendesk"""

        for identity in self.client.users.identities(id=zendesk_user_id):
            if identity.primary and identity.type == "email":
                return identity.id

    def update_primary_email(self, zendesk_user_id, email):
        """Update the primary email of the user."""
        identity_id = self.get_primary_email_identity(zendesk_user_id)
        self.client.users.identities.update(
            user=zendesk_user_id, identity=ZendeskIdentity(id=identity_id, value=email)
        )

    def create_ticket(self, user, ticket_fields):
        """Create a ticket in Zendesk."""
        custom_fields = [
            {"id": settings.ZENDESK_PRODUCT_FIELD_ID, "value": ticket_fields.get("product")},
            {"id": settings.ZENDESK_OS_FIELD_ID, "value": ticket_fields.get("os")},
            {"id": settings.ZENDESK_COUNTRY_FIELD_ID, "value": ticket_fields.get("country")},
        ]
        ticket_kwargs = {
            "subject": ticket_fields.get("subject")
            or f"{ticket_fields.get('product_title', 'Product')} support",
            "comment": {"body": ticket_fields.get("description") or str(NO_RESPONSE)},
            "ticket_form_id": settings.ZENDESK_TICKET_FORM_ID,
        }

        # If this is the normal, athenticated form we want to use the category field
        if user.is_authenticated:
            custom_fields.append(
                {"id": settings.ZENDESK_CATEGORY_FIELD_ID, "value": ticket_fields.get("category")},
            )
        # If this is the loginless form we want to use the contact label field (tag)
        # and fix the category field to be "accounts"
        else:
            custom_fields.extend(
                [
                    {
                        "id": settings.ZENDESK_CONTACT_LABEL_ID,
                        "value": ticket_fields.get("category"),
                    },
                    {"id": settings.ZENDESK_CATEGORY_FIELD_ID, "value": "accounts"},
                ]
            )
            ticket_kwargs.update({"tags": [LOGINLESS_TAG]})
        ticket_kwargs.update({"custom_fields": custom_fields})
        ticket = Ticket(**ticket_kwargs)

        if user.is_authenticated:
            if user.profile.zendesk_id:
                # TODO: is this necessary if we're
                # updating users as soon as they're updated locally?
                ticket.requester_id = self.update_user(user).id
            else:
                ticket.requester_id = self.create_user(user).id
        else:
            ticket.requester_id = self.create_user(user, email=ticket_fields.get("email", "")).id
        return self.client.tickets.create(ticket)
