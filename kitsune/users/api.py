import json
from datetime import datetime, timedelta
from importlib import import_module
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import Group, Permission, User
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, Q
from django.db.models.functions import Now
from django.http import Http404, JsonResponse
from django.utils.encoding import force_str
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from kitsune.access.decorators import group_required, login_required
from kitsune.questions.models import Answer
from kitsune.questions.utils import num_answers, num_questions, num_solutions
from kitsune.sumo.api_utils import DateTimeUTCField, OrderingFilter, PermissionMod
from kitsune.sumo.decorators import json_view
from kitsune.users.models import Profile, Setting
from kitsune.users.templatetags.jinja_helpers import profile_avatar


def display_name_or_none(user):
    try:
        return user.profile.name
    except (Profile.DoesNotExist, AttributeError):
        return None


class TimezoneField(serializers.Field):
    def to_representation(self, obj):
        return force_str(obj)

    def to_internal_value(self, data):
        try:
            return ZoneInfo(str(data))
        except ZoneInfoNotFoundError:
            raise ValidationError("Unknown timezone")


@login_required
@require_GET
@json_view
def usernames(request):
    """An API to provide auto-complete data for user names."""
    term = request.GET.get("term", "")
    query = request.GET.get("query", "")
    pre = term or query

    if not pre:
        return []
    if not request.user.is_authenticated:
        return []

    users = (
        User.objects.filter(is_active=True)
        .exclude(profile__is_fxa_migrated=False)
        .filter(Q(username__istartswith=pre) | Q(profile__name__istartswith=pre))
        .select_related("profile")
    )[:10]

    autocomplete_list = []
    exact_match_in_list = False

    for user in users:
        if user.username.lower() == pre.lower():
            exact_match_in_list = True
        autocomplete_list.append(
            {
                "username": user.username,
                "display_name": display_name_or_none(user),
                "avatar": profile_avatar(user, 24),
            }
        )

    if not exact_match_in_list:
        # The front-end dropdown which uses this API requires the exact match to be in the list
        # if it exists, so that user can be selected. Our code above won't necessarily always
        # return an exact match, even if it exists, so if it's missing attempt to fetch it and
        # prepend it to the list
        try:
            exact_match = (
                User.objects.filter(username__iexact=pre)
                .filter(is_active=True)
                .select_related("profile")
                .get()
            )
            autocomplete_list = [{"username": exact_match.username, "display_name": display_name_or_none(exact_match), "avatar": profile_avatar(exact_match, 24)}, *autocomplete_list]
        except User.DoesNotExist:
            pass

    return autocomplete_list


@api_view(["GET"])
@permission_classes((IsAuthenticated,))
def test_auth(request):
    return Response(
        {
            "username": request.user.username,
            "authorized": True,
        }
    )


class OnlySelf(permissions.BasePermission):
    """
    Only allows operations when the current user is the object in question.

    Intended for use with PermissionsFields.

    TODO: This should be tied to user and object permissions better, but
    for now this is a bandaid.
    """

    def has_object_permission(self, request, view, obj):
        request_user = getattr(request, "user", None)
        user = getattr(obj, "user", None)
        return request_user == user


class OnlySelfEdits(OnlySelf):
    """
    Only allow users/profiles to be edited and deleted by themselves.

    TODO: This should be tied to user and object permissions better, but
    for now this is a bandaid.
    """

    def has_object_permission(self, request, view, obj):
        # SAFE_METHODS is a list containing all the read-only methods.
        if request.method in permissions.SAFE_METHODS:
            return True
        else:
            return super().has_object_permission(request, view, obj)


class UserSettingSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        required=False, write_only=True, queryset=User.objects.all()
    )

    class Meta:
        model = Setting
        fields = ("name", "value", "user")

    def get_identity(self, obj):
        return obj["name"]


class ProfileSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username")
    display_name = serializers.CharField(source="name", required=False)
    date_joined = DateTimeUTCField(source="user.date_joined", read_only=True)
    avatar = serializers.SerializerMethodField("get_avatar_url")
    email = PermissionMod(serializers.EmailField, permissions=[OnlySelf])(
        source="user.email", required=True
    )
    settings = PermissionMod(UserSettingSerializer, permissions=[OnlySelf])(
        many=True, read_only=True
    )
    helpfulness = serializers.ReadOnlyField(source="answer_helpfulness")
    answer_count = serializers.SerializerMethodField()
    question_count = serializers.SerializerMethodField()
    solution_count = serializers.SerializerMethodField()
    last_answer_date = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    timezone = TimezoneField(required=False)

    class Meta:
        model = Profile
        fields = [
            "answer_count",
            "avatar",
            "bio",
            "city",
            "country",
            "date_joined",
            "display_name",
            "email",
            "community_mozilla_org",
            "helpfulness",
            "id",
            "matrix_handle",
            "is_active",
            "last_answer_date",
            "locale",
            "people_mozilla_org",
            "question_count",
            "settings",
            "solution_count",
            "timezone",
            "twitter",
            "username",
            "website",
        ]

    def get_avatar_url(self, profile):
        request = self.context.get("request")
        size = request.GET.get("avatar_size", 200) if request else 200
        return profile_avatar(profile.user, size=size)

    def get_question_count(self, profile):
        return num_questions(profile.user)

    def get_answer_count(self, profile):
        return num_answers(profile.user)

    def get_solution_count(self, profile):
        return num_solutions(profile.user)

    def get_last_answer_date(self, profile):
        last_answer = profile.user.answers.order_by("-created").first()
        return last_answer.created if last_answer else None


class ProfileFKSerializer(ProfileSerializer):
    class Meta(ProfileSerializer.Meta):
        fields = [
            "username",
            "display_name",
            "avatar",
        ]


class ProfileViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    # User usernames instead of ids in urls.
    lookup_field = "user__username"
    # Usernames sometimes contain periods so we want to change the regex from the default '[^/.]+'
    lookup_value_regex = "[^/]+"
    permission_classes = [
        OnlySelfEdits,
    ]
    filter_backends = [
        DjangoFilterBackend,
        OrderingFilter,
    ]
    filterset_fields: list[str] = []
    ordering_fields: list[str] = []
    # Default, if not overwritten
    ordering = ("-user__date_joined",)

    number_blacklist = [666, 69]

    # This is routed to /api/2/user/weekly-solutions/
    def weekly_solutions(self, request, **kwargs):
        """
        Return the most helpful users in the past week.
        """
        start = datetime.now() - timedelta(days=7)
        # Get a list of top 10 users and the number of solutions they have in the last week.
        # It looks like [{'creator__username': 'bob', 'creator__count': 12}, ...]
        # This uses ``username`` instead of ``id``, because ``username`` appears
        # in the output of ``ProfileFKSerializer``, whereas ``id`` does not.
        # It also reverse order the dictionary according to amount of solution so that we can get
        # get top contributors
        # Use "__range" to ensure the database index is used in Postgres.
        raw_counts = (
            Answer.objects.exclude(solution_for=None)
            .filter(created__range=(start, Now()))
            .values("creator__username")
            .annotate(Count("creator"))
            .order_by("creator__count")
            .reverse()[:10]
        )

        # Turn that list into a dictionary from username -> count.
        username_to_count = {u["creator__username"]: u["creator__count"] for u in raw_counts}

        # Get all the profiles mentioned in the above.
        profiles = Profile.objects.filter(user__username__in=list(username_to_count.keys()))
        result = ProfileFKSerializer(instance=profiles, many=True).data

        # Pair up the profiles and the solution counts.
        for u in result:
            u["weekly_solutions"] = username_to_count[u["username"]]

        result.sort(key=lambda u: u["weekly_solutions"], reverse=True)
        return Response(result)


@group_required("Staff")
@require_POST
@csrf_exempt
def create_test_user(request):
    """
    Creates a new test user and a session for that user, returning the test user's session cookie.
    """
    if not (settings.DEV and settings.ENABLE_TESTING_ENDPOINTS):
        raise Http404

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid JSON payload."}, status=400)

    if not (username := data.get("username")):
        return JsonResponse({"message": 'Invalid JSON payload (missing "username").'}, status=400)

    try:
        test_user = User.objects.create_user(username=username)
    except IntegrityError:
        return JsonResponse({"message": f'Username "{username}" already exists.'}, status=409)

    if codenames := data.get("permissions"):
        if not isinstance(codenames, list):
            return JsonResponse(
                {"message": 'Invalid JSON payload ("permissions" is not a list).'}, status=400
            )

        for codename in codenames:
            try:
                permission = Permission.objects.get(codename=codename)
            except Permission.DoesNotExist:
                return JsonResponse(
                    {"message": f'Permission "{codename}" does not exist.'}, status=400
                )
            else:
                test_user.user_permissions.add(permission)

    if group_names := data.get("groups"):
        if not isinstance(group_names, list):
            return JsonResponse(
                {"message": 'Invalid JSON payload ("groups" is not a list).'}, status=400
            )

        for name in group_names:
            try:
                group = Group.objects.get(name=name)
            except Group.DoesNotExist:
                return JsonResponse({"message": f'Group "{name}" does not exist.'}, status=400)
            else:
                test_user.groups.add(group)

    Profile.objects.create(user=test_user, is_fxa_migrated=True)

    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session[SESSION_KEY] = str(test_user.pk)
    session[BACKEND_SESSION_KEY] = "kitsune.users.auth.FXAAuthBackend"
    session[HASH_SESSION_KEY] = test_user.get_session_auth_hash()
    session.create()

    return JsonResponse(
        {
            "username": test_user.username,
            "cookies": [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session.session_key,
                    "max-age": 60 * 60,  # 1 hour
                    "path": settings.SESSION_COOKIE_PATH,
                    "domain": Site.objects.get_current().domain,
                    "secure": settings.SESSION_COOKIE_SECURE,
                    "httponly": settings.SESSION_COOKIE_HTTPONLY,
                    "samesite": settings.SESSION_COOKIE_SAMESITE,
                },
            ],
        }
    )

@group_required("Staff")
@require_POST
@csrf_exempt
def trigger_delete(request):
    """
    Deletes a given test user.
    """
    if not (settings.DEV and settings.ENABLE_TESTING_ENDPOINTS):
        raise Http404

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid JSON payload."}, status=400)

    if not (username := data.get("username")):
        return JsonResponse({"message": 'Invalid JSON payload (missing "username").'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({"message": f"{username} does not exist."}, status=404)
    else:
        user.delete()

    return JsonResponse({"message": f"{username} was successfully deleted!"})
