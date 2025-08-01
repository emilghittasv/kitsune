import datetime

from django.contrib.auth.models import User
from django.db import models

from kitsune import kbforums
from kitsune.sumo.models import ModelBase
from kitsune.sumo.templatetags.jinja_helpers import urlparams, wiki_to_html
from kitsune.sumo.urlresolvers import reverse
from kitsune.tidings.models import NotificationsMixin
from kitsune.wiki.models import Document


def _last_post_from(posts, exclude_post=None):
    """Return the most recent post in the given set, excluding the given post.

    If there are none, return None.

    """
    if exclude_post:
        posts = posts.exclude(id=exclude_post.id)
    posts = posts.order_by("-created")
    try:
        return posts[0]
    except IndexError:
        return None


class ThreadLockedError(Exception):
    """Trying to create a post in a locked thread."""


class Thread(NotificationsMixin, ModelBase):
    title = models.CharField(max_length=255)
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    created = models.DateTimeField(default=datetime.datetime.now, db_index=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wiki_thread_set")
    last_post = models.ForeignKey(
        "Post", on_delete=models.CASCADE, related_name="last_post_in", null=True
    )
    replies = models.IntegerField(default=0)
    is_locked = models.BooleanField(default=False)
    is_sticky = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-is_sticky", "-last_post__created"]
        permissions = (
            ("lock_thread", "Can lock KB threads"),
            ("sticky_thread", "Can sticky KB threads"),
        )

    @property
    def last_page(self):
        """Returns the page number for the last post."""
        return self.replies // kbforums.POSTS_PER_PAGE + 1

    def __str__(self):
        return self.title

    def new_post(self, creator, content):
        """Create a new post, if the thread is unlocked."""
        if self.is_locked:
            raise ThreadLockedError

        return self.post_set.create(creator=creator, content=content)

    def get_absolute_url(self):
        return reverse(
            "wiki.discuss.posts",
            locale=self.document.locale,
            kwargs={"document_slug": self.document.slug, "thread_id": self.id},
        )

    def update_last_post(self, exclude_post=None):
        """Set my last post to the newest, excluding the given post."""
        last = _last_post_from(self.post_set, exclude_post=exclude_post)
        self.last_post = last
        # If self.last_post is None, and this was called from Post.delete,
        # then Post.delete will erase the thread, as well.


class Post(ModelBase):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE)
    content = models.TextField()
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wiki_post_set")
    created = models.DateTimeField(default=datetime.datetime.now, db_index=True)
    updated = models.DateTimeField(default=datetime.datetime.now, db_index=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="wiki_post_last_updated_by", null=True
    )

    class Meta:
        ordering = ["created"]

    def __str__(self):
        return self.content[:50]

    def save(self, *args, **kwargs):
        """
        Override save method to update parent thread info and take care of
        created and updated.
        """
        new = self.id is None
        now = datetime.datetime.now()

        if new:
            self.created = now
        self.updated = now

        super().save(*args, **kwargs)

        if new:
            self.thread.replies = self.thread.post_set.count() - 1
            self.thread.last_post = self
            self.thread.save()

    def delete(self, *args, **kwargs):
        """Override delete method to update parent thread info."""
        thread = Thread.objects.get(pk=self.thread.id)
        if thread.last_post_id and thread.last_post_id == self.id:
            thread.update_last_post(exclude_post=self)
        thread.replies = thread.post_set.count() - 2
        thread.save()

        super().delete(*args, **kwargs)
        # If I was the last post in the thread, delete the thread.
        if thread.last_post is None:
            thread.delete()

    @property
    def page(self):
        """Get the page of the thread on which this post is found."""
        t = self.thread
        earlier = t.post_set.filter(created__lte=self.created).count() - 1
        if earlier < 1:
            return 1
        return earlier // kbforums.POSTS_PER_PAGE + 1

    def get_absolute_url(self):
        query = {}
        if self.page > 1:
            query["page"] = self.page

        url_ = reverse(
            "wiki.discuss.posts",
            locale=self.thread.document.locale,
            kwargs={
                "document_slug": self.thread.document.slug,
                "thread_id": self.thread.id,
            },
        )
        return urlparams(url_, hash="post-{}".format(self.id), **query)

    @property
    def content_parsed(self):
        return wiki_to_html(self.content)
