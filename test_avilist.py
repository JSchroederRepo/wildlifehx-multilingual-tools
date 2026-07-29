#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the AviList name override. Network calls are mocked out.

    python3 -m unittest discover -v
"""
import unittest
from unittest import mock

import app

# Gavia immer is in AviList as "Common Loon"; Oressochen jubatus is one of the
# ~0.5% of eBird species AviList lists under another genus (Neochen jubata), so
# it must fall through to the eBird names.
MATCHED_SCI = "Gavia immer"
MATCHED_AVILIST_EN = "Common Loon"
UNMATCHED_SCI = "Oressochen jubatus"


class AvilistLookupTest(unittest.TestCase):
    def test_bundled_lookup_loads(self):
        species = app.load_avilist()
        self.assertGreater(len(species), 10000)

    def test_matched_species_uses_avilist_english(self):
        sci, english = app.avilist_names(MATCHED_SCI, "Great Northern Diver")
        self.assertEqual(sci, MATCHED_SCI)
        self.assertEqual(english, MATCHED_AVILIST_EN)

    def test_match_ignores_case_and_extra_whitespace(self):
        sci, english = app.avilist_names("  gavia   IMMER ", "Great Northern Diver")
        self.assertEqual(sci, MATCHED_SCI)  # canonical AviList spelling
        self.assertEqual(english, MATCHED_AVILIST_EN)

    def test_unmatched_species_falls_back_to_ebird(self):
        sci, english = app.avilist_names(UNMATCHED_SCI, "Orinoco Goose")
        self.assertEqual(sci, UNMATCHED_SCI)
        self.assertEqual(english, "Orinoco Goose")

    def test_subspecies_and_hybrids_fall_back_to_ebird(self):
        for sci in ("Larus argentatus argenteus", "Anas platyrhynchos x Anas acuta"):
            self.assertEqual(app.avilist_names(sci, "eBird name"), (sci, "eBird name"))


class TripReportTableTest(unittest.TestCase):
    """The eBird trip-report tab: /api?trip=<id>."""

    def test_english_column_prefers_avilist_then_falls_back(self):
        taxa = [
            {"speciesCode": "comloo", "sciName": MATCHED_SCI,
             "commonName": "Great Northern Diver", "numIndividuals": 3},
            {"speciesCode": "origoo1", "sciName": UNMATCHED_SCI,
             "commonName": "Orinoco Goose", "numIndividuals": 1},
        ]
        empty_maps = {locale: {} for locale, _, _, _ in app.NAME_COLUMNS}
        with mock.patch.object(app, "get_trip_meta", return_value={}), \
             mock.patch.object(app, "get_trip_taxa", return_value=taxa), \
             mock.patch.object(app, "build_name_maps", return_value=empty_maps):
            _, rows = app.build_table("546161")

        self.assertEqual(rows[0]["scientific_name"], MATCHED_SCI)
        self.assertEqual(rows[0]["english_name"], MATCHED_AVILIST_EN)
        self.assertEqual(rows[0]["obs_count"], 3)
        self.assertEqual(rows[1]["scientific_name"], UNMATCHED_SCI)
        self.assertEqual(rows[1]["english_name"], "Orinoco Goose")


class TranslatorBirdNamesTest(unittest.TestCase):
    """The species-translator tab: /api?birdnames=<scientific name>."""

    def setUp(self):
        app._SCI_INDEX = None
        self.addCleanup(setattr, app, "_SCI_INDEX", None)

    @staticmethod
    def _taxonomy(locale, sci=MATCHED_SCI):
        common = "eBird Loon" if locale == "en" else locale + " Loon"
        return {"comloo": {"sci_name": sci, "common_name": common}}

    def test_english_from_avilist_translations_from_ebird(self):
        with mock.patch.object(app, "get_taxonomy", side_effect=self._taxonomy):
            res = app.get_bird_names(MATCHED_SCI)

        self.assertTrue(res["found"])
        self.assertEqual(res["scientific"], MATCHED_SCI)
        self.assertEqual(res["english"], MATCHED_AVILIST_EN)
        self.assertEqual(res["names"]["en"], MATCHED_AVILIST_EN)
        # every non-English locale still comes straight from eBird
        for locale in app.BIRD_NAME_LOCALES:
            if locale != "en":
                self.assertEqual(res["names"][locale], locale + " Loon")

    def test_unmatched_species_keeps_ebird_english(self):
        taxonomy = lambda locale: self._taxonomy(locale, sci=UNMATCHED_SCI)
        with mock.patch.object(app, "get_taxonomy", side_effect=taxonomy):
            res = app.get_bird_names(UNMATCHED_SCI)

        self.assertEqual(res["scientific"], UNMATCHED_SCI)
        self.assertEqual(res["english"], "eBird Loon")

    def test_unknown_species_reports_not_found(self):
        with mock.patch.object(app, "get_taxonomy", side_effect=self._taxonomy):
            res = app.get_bird_names("Not abird")
        self.assertEqual(res, {"found": False})


if __name__ == "__main__":
    unittest.main()
