from kitsune.products.tests import ProductFactory, TopicFactory
from kitsune.sumo.tests import TestCase


class TopicModelTests(TestCase):
    def test_path(self):
        """Verify that the path property works."""
        p = ProductFactory(slug="p")
        t1 = TopicFactory(product=p, slug="t1")
        t2 = TopicFactory(product=p, slug="t2", parent=t1)
        t3 = TopicFactory(product=p, slug="t3", parent=t2)

        self.assertEqual(t1.path, [t1.slug])
        self.assertEqual(t2.path, [t1.slug, t2.slug])
        self.assertEqual(t3.path, [t1.slug, t2.slug, t3.slug])

    def test_absolute_url(self):
        p = ProductFactory()
        t = TopicFactory(product=p)
        expected = f"/en-US/products/{p.slug}/{t.slug}"
        actual = t.get_absolute_url(p.slug)
        self.assertEqual(actual, expected)

    def test_absolute_url_subtopic(self):
        p = ProductFactory()
        t1 = TopicFactory(product=p)
        t2 = TopicFactory(parent=t1, product=p)
        expected = f"/en-US/products/{p.slug}/{t1.slug}/{t2.slug}"
        actual = t2.get_absolute_url(p.slug)
        self.assertEqual(actual, expected)

    def test_absolute_url_topics(self):
        t = TopicFactory()
        expected = f"/en-US/topics/{t.slug}"
        actual = t.get_absolute_url()
        self.assertEqual(actual, expected)


class ProductModelTests(TestCase):
    def test_absolute_url(self):
        p = ProductFactory()
        expected = "/en-US/products/{p}".format(p=p.slug)
        actual = p.get_absolute_url()
        self.assertEqual(actual, expected)
