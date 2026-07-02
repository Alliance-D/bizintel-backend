from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BusinessCategory:
    key: str
    label_en: str
    label_rw: str
    description_en: str
    description_rw: str
    osm_rules: list[tuple[str, str]]
    min_osm_count_note: str
    weights: dict[str, float]
    examples: list[str]


# Priority categories for the next backend and ML implementation.
# The order follows data availability from OSM and product usefulness.
BUSINESS_CATEGORIES: list[BusinessCategory] = [
    BusinessCategory(
        key='pharmacy',
        label_en='Pharmacy',
        label_rw='Farumasi',
        description_en='Medicine access and health retail locations',
        description_rw='Aho serivisi za farumasi n’imiti byoroshye kugerwaho',
        osm_rules=[('amenity', 'pharmacy'), ('healthcare', 'pharmacy')],
        min_osm_count_note='Strong OSM coverage in Kigali, more than 200 mapped pharmacies reported by the project team',
        weights={'demand': 0.30, 'access': 0.28, 'activity': 0.18, 'competition': 0.16, 'welfare': 0.08},
        examples=['pharmacy', 'chemist', 'health retail'],
    ),
    BusinessCategory(
        key='restaurant',
        label_en='Restaurant and fast food',
        label_rw='Resitora n’aho bagurisha ibiryo byihuse',
        description_en='Food service, restaurants and fast food businesses',
        description_rw='Ubucuruzi bwa resitora n’ahagurishirizwa ibiryo byihuse',
        osm_rules=[('amenity', 'restaurant'), ('amenity', 'fast_food'), ('amenity', 'food_court')],
        min_osm_count_note='Good OSM coverage in Kigali, more than 150 restaurants and fast food places reported by the project team',
        weights={'demand': 0.25, 'access': 0.24, 'activity': 0.31, 'competition': 0.12, 'welfare': 0.08},
        examples=['restaurant', 'fast_food', 'takeaway'],
    ),
    BusinessCategory(
        key='cafe',
        label_en='Café',
        label_rw='Kafe',
        description_en='Coffee, snack, study and social meeting places',
        description_rw='Aho kunywera ikawa, gufata utuntu, kwiga cyangwa guhurira',
        osm_rules=[('amenity', 'cafe')],
        min_osm_count_note='Moderate OSM coverage in Kigali, more than 50 cafés reported by the project team',
        weights={'demand': 0.22, 'access': 0.22, 'activity': 0.34, 'competition': 0.14, 'welfare': 0.08},
        examples=['cafe', 'coffee shop', 'tea room'],
    ),
    BusinessCategory(
        key='grocery',
        label_en='Supermarket and grocery',
        label_rw='Supamaketi n’iduka ry’ibiribwa',
        description_en='Daily household goods, supermarkets and grocery stores',
        description_rw='Amaduka y’ibiribwa n’ibikoresho byo mu rugo bya buri munsi',
        osm_rules=[('shop', 'supermarket'), ('shop', 'grocery'), ('shop', 'convenience'), ('shop', 'greengrocer')],
        min_osm_count_note='Moderate OSM coverage in Kigali, more than 60 supermarkets or grocery stores reported by the project team',
        weights={'demand': 0.39, 'access': 0.20, 'activity': 0.16, 'competition': 0.17, 'welfare': 0.08},
        examples=['supermarket', 'grocery', 'convenience store'],
    ),
    BusinessCategory(
        key='salon',
        label_en='Salon and personal care',
        label_rw='Saloon n’ubwiza',
        description_en='Hair, beauty, barbering and personal care services',
        description_rw='Serivisi z’imisatsi, ubwiza, kogosha n’isuku y’umuntu',
        osm_rules=[('shop', 'hairdresser'), ('shop', 'beauty'), ('shop', 'cosmetics'), ('amenity', 'barber')],
        min_osm_count_note='Lower OSM coverage in Kigali, around 19 salon related places reported by the project team, so field validation matters more',
        weights={'demand': 0.34, 'access': 0.20, 'activity': 0.22, 'competition': 0.16, 'welfare': 0.08},
        examples=['hairdresser', 'beauty salon', 'barber', 'cosmetics'],
    ),
]

CATEGORY_ALIASES: dict[str, str] = {
    'pharmacies': 'pharmacy',
    'chemist': 'pharmacy',
    'medicine': 'pharmacy',
    'fast_food': 'restaurant',
    'fast-food': 'restaurant',
    'food': 'restaurant',
    'restaurants': 'restaurant',
    'coffee': 'cafe',
    'cafes': 'cafe',
    'café': 'cafe',
    'supermarket': 'grocery',
    'supermarkets': 'grocery',
    'grocery_store': 'grocery',
    'grocery shop': 'grocery',
    'convenience': 'grocery',
    'hairdresser': 'salon',
    'barber': 'salon',
    'barbershop': 'salon',
    'beauty': 'salon',
    'beauty_salon': 'salon',
    'cosmetics': 'salon',
    'personal_care': 'salon',
}


def normalise_category(value: str | None) -> str:
    raw = (value or 'pharmacy').strip().lower().replace('&', 'and')
    raw = raw.replace(' ', '_')
    return CATEGORY_ALIASES.get(raw, raw if raw in {c.key for c in BUSINESS_CATEGORIES} else 'pharmacy')


def category_map() -> dict[str, BusinessCategory]:
    return {category.key: category for category in BUSINESS_CATEGORIES}


def category_payload(lang: str = 'en') -> list[dict[str, Any]]:
    use_rw = lang.lower().startswith('rw') or lang.lower().startswith('kin')
    rows = []
    for category in BUSINESS_CATEGORIES:
        rows.append({
            'key': category.key,
            'label': category.label_rw if use_rw else category.label_en,
            'label_en': category.label_en,
            'label_rw': category.label_rw,
            'description': category.description_rw if use_rw else category.description_en,
            'description_en': category.description_en,
            'description_rw': category.description_rw,
            'osm_rules': [{'key': k, 'value': v} for k, v in category.osm_rules],
            'coverage_note': category.min_osm_count_note,
            'weights': category.weights,
            'examples': category.examples,
        })
    return rows
