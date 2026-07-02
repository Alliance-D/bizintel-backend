from __future__ import annotations

from typing import Any

UI_TRANSLATIONS: dict[str, dict[str, str]] = {
    'en': {
        'map': 'Map', 'compare': 'Compare', 'insights': 'Insights', 'saved': 'Saved', 'reports': 'Reports', 'sign_in': 'Sign in',
        'opportunity': 'Opportunity', 'scout': 'Scout', 'competitive': 'Competitive',
        'demand': 'Demand', 'access': 'Access', 'activity': 'Activity', 'competition': 'Competition', 'confidence': 'Confidence',
        'save_location': 'Save location', 'create_report': 'Create report', 'field_check': 'Field check',
        'select_grid_cell': 'Select a grid cell',
    },
    'rw': {
        'map': 'Ikarita', 'compare': 'Gereranya', 'insights': 'Isesengura', 'saved': 'Ibyabitswe', 'reports': 'Raporo', 'sign_in': 'Injira',
        'opportunity': 'Amahirwe', 'scout': 'Suzuma ahantu', 'competitive': 'Ipiganwa',
        'demand': 'Ubukenewe', 'access': 'Kugerwaho', 'activity': 'Ibikorwa by’ubucuruzi', 'competition': 'Ipiganwa', 'confidence': 'Icyizere cy’amakuru',
        'save_location': 'Bika ahantu', 'create_report': 'Kora raporo', 'field_check': 'Isuzuma ryo ku rubuga',
        'select_grid_cell': 'Hitamo agace ku ikarita',
    },
}

TUTORIAL_STEPS: dict[str, list[dict[str, Any]]] = {
    'en': [
        {'key': 'category', 'title': 'Choose a business category', 'body': 'Start with pharmacy, restaurant, café, grocery or salon so the map can score the right kind of business', 'target': 'category-selector'},
        {'key': 'opportunity', 'title': 'Scan opportunity zones', 'body': 'Opportunity mode shows where demand, access, activity and supply conditions look strongest', 'target': 'mode-opportunity'},
        {'key': 'lens', 'title': 'Switch lenses', 'body': 'Use demand, access, activity, competition and confidence lenses to understand why each grid cell changes colour', 'target': 'lens-panel'},
        {'key': 'scout', 'title': 'Drop a pin', 'body': 'Scout mode checks one exact candidate location before calling a landlord or visiting the site', 'target': 'mode-scout'},
        {'key': 'competitive', 'title': 'Read competition pressure', 'body': 'Competitive mode helps you see crowded cells and underserved nearby pockets', 'target': 'mode-competitive'},
        {'key': 'save_report', 'title': 'Save, compare and report', 'body': 'Save promising places, compare alternatives, create reports and prepare field checks before committing', 'target': 'result-actions'},
    ],
    'rw': [
        {'key': 'category', 'title': 'Hitamo ubwoko bw’ubucuruzi', 'body': 'Tangira uhitamo farumasi, resitora, kafe, iduka ry’ibiribwa cyangwa saloon kugira ngo ikarita isuzume neza', 'target': 'category-selector'},
        {'key': 'opportunity', 'title': 'Reba uduce dufite amahirwe', 'body': 'Uburyo bwa Opportunity bwerekana aho ubukenewe, kugerwaho, ibikorwa n’isoko bigaragara ko bikomeye', 'target': 'mode-opportunity'},
        {'key': 'lens', 'title': 'Hindura uko ureba amakuru', 'body': 'Koresha ubukenewe, kugerwaho, ibikorwa, ipiganwa n’icyizere cy’amakuru kugira ngo usobanukirwe impamvu agace gahindura ibara', 'target': 'lens-panel'},
        {'key': 'scout', 'title': 'Shyira pin ku ikarita', 'body': 'Scout isuzuma ahantu nyirizina mbere yo guhamagara nyiri inzu cyangwa gusura ahantu', 'target': 'mode-scout'},
        {'key': 'competitive', 'title': 'Soma igitutu cy’ipiganwa', 'body': 'Competitive igufasha kubona aho ipiganwa ari ryinshi n’uduce dushobora kuba tutaragerwaho bihagije', 'target': 'mode-competitive'},
        {'key': 'save_report', 'title': 'Bika, gereranya, ukore raporo', 'body': 'Bika ahantu hakomeye, ugereranye amahitamo, ukore raporo kandi utegure isuzuma ryo ku rubuga mbere yo kwiyemeza', 'target': 'result-actions'},
    ],
}


def locale_key(locale: str | None) -> str:
    raw = (locale or 'en').lower()
    return 'rw' if raw.startswith('rw') or raw.startswith('kin') else 'en'


def get_translations(locale: str | None = 'en') -> dict[str, Any]:
    lang = locale_key(locale)
    return {'locale': lang, 'strings': UI_TRANSLATIONS[lang]}


def get_tutorial(locale: str | None = 'en') -> dict[str, Any]:
    lang = locale_key(locale)
    return {'locale': lang, 'tutorial_key': 'first_visit', 'steps': TUTORIAL_STEPS[lang]}
