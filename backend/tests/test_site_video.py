# -*- coding: utf-8 -*-
"""Tests för klippen i landningssidans presentation.

The rule these protect: the presentation is a story, and a clip that does not
play its scene breaks it more visibly than a missing clip would. A landing
page is the first thing anyone sees of Matjakt.

Nothing here touches the network - scoring and file selection are pure
functions over the shape Pexels returns, which is where the risk is.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import video  # noqa: E402


def clip(slug, duration=8, width=1920, files=None):
    """A Pexels video the way the API returns it."""
    return {
        "id": abs(hash(slug)) % 10**7,
        "url": f"https://www.pexels.com/video/{slug}-1234567/",
        "duration": duration,
        "width": width,
        "height": 1080,
        "image": "https://images.pexels.com/x.jpg",
        "user": {"name": "Någon", "url": "https://www.pexels.com/@nagon"},
        "video_files": files if files is not None else [
            {"file_type": "video/mp4", "width": 1280, "height": 720, "link": "hd.mp4"},
        ],
    }


def scene(key="butiker"):
    return next(s for s in video.SCENES if s["key"] == key)


class SceneRelevance(unittest.TestCase):
    def test_clip_that_plays_the_scene_scores(self):
        self.assertGreater(
            video.score_clip(clip("shopping-cart-in-grocery-store-aisle"), scene()), 0)

    def test_one_incidental_word_is_not_enough(self):
        """"Food" appears in half of Pexels. On its own it is not evidence
        that a clip shows a supermarket, and letting it through is exactly
        how a presentation turns into a stock-footage reel."""
        self.assertEqual(video.score_clip(clip("a-bowl-of-food"), scene("butiker")), 0)

    def test_forbidden_subject_is_refused_however_well_it_matches(self):
        """Every other word fits the scene. It is still a clip about beer."""
        self.assertEqual(
            video.score_clip(clip("man-buying-beer-in-grocery-store-aisle-cart"),
                             scene("butiker")), 0)

    def test_too_short_to_loop_and_too_long_to_ship_are_both_refused(self):
        for duration in (2, 40):
            self.assertEqual(
                video.score_clip(clip("shopping-cart-grocery-store-aisle", duration),
                                 scene()), 0, f"{duration}s borde ha refuserats")

    def test_a_clip_with_no_slug_words_is_refused(self):
        """No slug means no evidence. Unknown is not the same as fine."""
        self.assertEqual(video.score_clip({"url": "", "duration": 8}, scene()), 0)

    def test_loop_length_is_preferred_over_a_longer_clip(self):
        short = video.score_clip(clip("shopping-cart-grocery-aisle-store", 9), scene())
        long = video.score_clip(clip("shopping-cart-grocery-aisle-store", 24), scene())
        self.assertGreater(short, long)


class RenditionChoice(unittest.TestCase):
    def test_smallest_acceptable_rendition_wins(self):
        """Pexels offers the same clip up to 4K. Shipping the biggest one to a
        phone is how a landing page becomes something people leave."""
        chosen = video.pick_file(clip("x", files=[
            {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "4k.mp4"},
            {"file_type": "video/mp4", "width": 1280, "height": 720, "link": "hd.mp4"},
            {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "fhd.mp4"},
        ]))
        self.assertEqual(chosen["link"], "hd.mp4")

    def test_a_too_small_rendition_is_not_chosen_just_for_being_small(self):
        """640px stretched to full width looks broken. Below the floor we take
        the next size up rather than the smallest file."""
        chosen = video.pick_file(clip("x", files=[
            {"file_type": "video/mp4", "width": 640, "height": 360, "link": "tiny.mp4"},
            {"file_type": "video/mp4", "width": 1280, "height": 720, "link": "hd.mp4"},
        ]))
        self.assertEqual(chosen["link"], "hd.mp4")

    def test_no_mp4_means_no_clip(self):
        self.assertIsNone(video.pick_file(clip("x", files=[
            {"file_type": "video/quicktime", "width": 1280, "link": "x.mov"}])))


class Manifest(unittest.TestCase):
    """The committed manifest is what the landing page actually reads."""

    def setUp(self):
        if not video.MANIFEST.exists():
            self.skipTest("clips.json saknas - kör fetch_site_video.py")
        self.clips = json.loads(video.MANIFEST.read_text(encoding="utf-8"))["clips"]

    def test_paths_are_relative_to_the_page_not_to_the_clip_directory(self):
        """Regression: the manifest said "video/x.mp4", which the page
        resolved against the site root. Every clip and poster 404'd and the
        presentation rendered as blank green tiles."""
        for key, clip_data in self.clips.items():
            if clip_data.get("status") != "ok":
                continue
            for field in ("src", "poster"):
                self.assertTrue(clip_data[field].startswith(video.WEB_PREFIX + "/"),
                                f"{key}.{field} = {clip_data[field]}")

    def test_every_referenced_file_exists(self):
        for key, clip_data in self.clips.items():
            if clip_data.get("status") != "ok":
                continue
            for field in ("src", "poster"):
                path = ROOT / "frontend" / clip_data[field]
                self.assertTrue(path.exists(), f"{key}: {path} saknas")

    def test_every_clip_records_where_it_came_from(self):
        """A clip we cannot show the origin of is a clip we cannot defend."""
        for key, clip_data in self.clips.items():
            if clip_data.get("status") != "ok":
                continue
            self.assertEqual(clip_data["license"], "Pexels License", key)
            self.assertTrue(clip_data["credit"], f"{key} saknar fotograf")
            self.assertTrue(clip_data["sourceUrl"].startswith("https://"), key)

    def test_clips_stay_light_enough_for_mobile_data(self):
        """Not a style rule. This is the number that decides whether someone
        on the bus ever sees the page."""
        total = sum(c.get("bytes", 0) for c in self.clips.values()
                    if c.get("status") == "ok")
        self.assertLess(total, 8_000_000, f"klippen väger {total/1e6:.1f} MB")

    def test_no_clip_is_used_twice(self):
        used = [c["pexelsId"] for c in self.clips.values() if c.get("status") == "ok"]
        self.assertEqual(len(used), len(set(used)), "samma klipp i två scener")


class Presentation(unittest.TestCase):
    def test_the_landing_page_renders_the_generated_block(self):
        index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("PRESENTATION:START", index)
        self.assertIn("site-film-scene", index)

    def test_every_clip_on_the_page_is_lazy_and_silent(self):
        """muted and playsinline are what let it autoplay on iOS at all;
        preload="none" is what keeps it from being downloaded before anyone
        has scrolled to it."""
        index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        for tag in index.split("<video")[1:]:
            attributes = tag.split(">")[0]
            for required in ("muted", "playsinline", 'preload="none"'):
                self.assertIn(required, attributes, f"saknar {required}")
            self.assertNotIn("autoplay", attributes,
                             "autoplay kringgår kontrollen av datasparläge")


if __name__ == "__main__":
    unittest.main()
