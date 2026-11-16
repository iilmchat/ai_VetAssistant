"""Гибридный поиск для RAG: BM25 + Reciprocal Rank Fusion (T-141).

Зачем BM25: векторный поиск по эмбеддингам «размывает» точные названия
препаратов, дозировки и редкие термины. Лексический BM25 по тем же чанкам
ловит буквальные совпадения и возвращает их в топ.

Особенность корпуса: статьи MSD Vet Manual лежат на английском, а вопросы
пользователей — на русском. Поэтому «чистый» BM25 по русскому запросу почти
не находит совпадений: слов ``ксилит`` в английском тексте нет. Чтобы
лексический поиск работал, запрос расширяется русско-английским глоссарием
(:data:`RU_EN_TERMS`): ``ксилитом`` → ``xylitol``. Расширение применяется
только к запросу, индекс остаётся как есть.

Модуль намеренно не тянет внешних зависимостей: BM25Okapi реализован здесь
же (~60 строк), чтобы production-образ не пересобирался ради нового пакета,
а тесты работали без сети. Формула и параметры — стандартные Okapi BM25.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

#: Токен: кириллица, латиница, цифры. Дефисы и пунктуация — разделители,
#: поэтому «1,5 мл/кг» даёт токены ``1``, ``5``, ``мл``, ``кг``.
TOKEN_PATTERN = re.compile(r"[а-яёa-z0-9]+")

#: Стандартные параметры Okapi BM25.
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75

#: Во сколько раз заголовок чанка весомее текста (токены заголовка
#: повторяются в мешке слов документа).
DEFAULT_TITLE_WEIGHT = 2.0

#: Вес русских токенов запроса, если для них нашёлся английский перевод.
#: Корпус MSD англоязычный, а три демо-файла — русские: без понижения веса
#: BM25 выбирает маленькие русские файлы вместо профильной статьи.
DEFAULT_RU_FALLBACK_WEIGHT = 0.25

#: Русско-английский глоссарий для расширения запроса.
#:
#: Ключи — русские основы (нижний регистр). Совпадением считается либо
#: точное равенство, либо префикс с окончанием не длиннее трёх символов:
#: ``ксилитом`` → ``ксилит`` → ``xylitol``. Короткие ключи (``кот``, ``шок``,
#: ``узи``) сравниваются только точно, чтобы не цеплять посторонние слова.
RU_EN_TERMS: Mapping[str, tuple[str, ...]] = {
    # Токсины и яды
    "ксилит": ("xylitol",),
    "виноград": ("grape",),
    "изюм": ("raisin",),
    "антифриз": ("antifreeze",),
    "этиленгликол": ("ethylene glycol",),
    "шоколад": ("chocolate",),
    "парацетамол": ("acetaminophen", "paracetamol"),
    "ибупрофен": ("ibuprofen",),
    "аспирин": ("aspirin",),
    "диклофенак": ("diclofenac",),
    "ивермектин": ("ivermectin",),
    "фомепизол": ("fomepizole",),
    "ацетилцистеин": ("acetylcysteine",),
    "фенобарбитал": ("phenobarbital",),
    "леветирацетам": ("levetiracetam",),
    "диазепам": ("diazepam",),
    "преднизолон": ("prednisolone", "prednisone"),
    "дексаметазон": ("dexamethasone",),
    "метоклопрамид": ("metoclopramide",),
    "омепразол": ("omeprazole",),
    "фуросемид": ("furosemide",),
    "эналаприл": ("enalapril",),
    "амоксициллин": ("amoxicillin",),
    "доксициклин": ("doxycycline",),
    "трамадол": ("tramadol",),
    "мелатонин": ("melatonin",),
    "антибиотик": ("antibiotic",),
    "антидот": ("antidote",),
    "пестицид": ("pesticide",),
    "инсектицид": ("insecticide",),
    "пиретроид": ("pyrethrin", "pyrethroid"),
    # Болезни и состояния
    "парвовирус": ("parvovirus", "parvoviral"),
    "чумк": ("distemper",),
    "бешенств": ("rabies",),
    "лейкоз": ("leukemia",),
    "дирофиляриоз": ("heartworm", "dirofilaria"),
    "гельминт": ("helminth", "worm"),
    "панкреатит": ("pancreatitis",),
    "гастрит": ("gastritis",),
    "энтерит": ("enteritis",),
    "гепатит": ("hepatitis",),
    "артрит": ("arthritis",),
    "артроз": ("arthrosis", "osteoarthritis"),
    "остеоартроз": ("osteoarthritis",),
    "отит": ("otitis",),
    "дерматит": ("dermatitis",),
    "дерматофит": ("dermatophytosis",),
    "лишай": ("ringworm",),
    "глауком": ("glaucoma",),
    "катаракт": ("cataract",),
    "тиреоид": ("thyroid",),
    "щитовид": ("thyroid",),
    "гипотиреоз": ("hypothyroidism",),
    "гипертиреоз": ("hyperthyroidism",),
    "астм": ("asthma",),
    "бронхит": ("bronchitis",),
    "пародонт": ("periodontal",),
    "кариес": ("caries",),
    "десн": ("gum", "gingiva"),
    "дёсен": ("gum", "gingiva"),
    "камень": ("tartar", "calculus"),
    "хроническ": ("chronic",),
    "аллерги": ("allergy", "allergic"),
    "анеми": ("anemia",),
    "обезвоживан": ("dehydration",),
    "эпилепс": ("epilepsy", "seizure"),
    "эпилепт": ("epilepsy", "seizure"),
    "статус": ("status", "status epilepticus"),
    "опас": ("dangerous", "risk", "fatal"),
    "интоксикац": ("toxicosis", "poisoning"),
    "отравлен": ("poisoning", "toxicosis"),
    "токсич": ("toxic", "toxicity"),
    # Симптомы
    "симптом": ("sign", "clinical"),
    "признак": ("sign",),
    "рвот": ("vomiting", "vomit"),
    "диаре": ("diarrhea",),
    "понос": ("diarrhea",),
    "запор": ("constipation",),
    "кашел": ("cough",),
    "одышк": ("dyspnea", "breathing"),
    "лихорадк": ("fever",),
    "температур": ("temperature", "fever"),
    "аппетит": ("appetite", "anorexia"),
    "вялост": ("lethargy", "weakness"),
    "слабост": ("weakness",),
    "судорог": ("seizure", "convulsion"),
    "приступ": ("seizure", "episode"),
    "паралич": ("paralysis",),
    "кровотечен": ("bleeding", "hemorrhage"),
    "зуд": ("itch", "pruritus"),
    # Анатомия и физиология
    "печен": ("liver", "hepatic"),
    "почк": ("kidney", "renal"),
    "почек": ("kidney", "renal"),
    "почечн": ("kidney", "renal"),
    "сердц": ("heart", "cardiac"),
    "желудк": ("stomach", "gastric"),
    "кишечн": ("intestine", "intestinal"),
    "мочев": ("urinary", "bladder"),
    "кровь": ("blood",),
    "кож": ("skin",),
    "глаз": ("eye",),
    "ухо": ("ear",),
    "уши": ("ear",),
    "зуб": ("tooth", "dental"),
    "кост": ("bone",),
    "сустав": ("joint",),
    "мышц": ("muscle",),
    "нерв": ("nerve", "nervous"),
    "мозг": ("brain",),
    "спинн": ("spinal",),
    # Животные
    "собак": ("dog", "canine"),
    "кошк": ("cat", "feline"),
    "кошек": ("cat", "feline"),
    "щенк": ("puppy",),
    "котен": ("kitten",),
    "кот": ("cat",),
    "кота": ("cat",),
    "коту": ("cat",),
    "котов": ("cat",),
    "кролик": ("rabbit",),
    "птиц": ("bird",),
    "лошад": ("horse",),
    "хорьк": ("ferret",),
    "хорек": ("ferret",),
    # Терапия и уход
    "лечен": ("treatment", "therapy"),
    "терапи": ("therapy", "treatment"),
    "дозировк": ("dosage", "dose"),
    "доза": ("dose",),
    "дозы": ("dose",),
    "дозе": ("dose",),
    "дозу": ("dose",),
    "профилактик": ("prevention", "prophylaxis"),
    "вакцин": ("vaccine", "vaccination"),
    "прививк": ("vaccine", "vaccination"),
    "диагноз": ("diagnosis",),
    "анализ": ("test", "analysis"),
    "узи": ("ultrasound",),
    "рентген": ("radiograph", "x-ray"),
    "операц": ("surgery",),
    "диет": ("diet",),
    "корм": ("food", "diet"),
    "кормлен": ("feeding",),
    "беременн": ("pregnancy", "pregnant"),
    "роды": ("labor", "parturition"),
    "экстренн": ("emergency",),
    "срочн": ("emergency", "urgent"),
    "ветеринар": ("veterinarian", "veterinary"),
}


def _normalize_latin_plural(token: str) -> str:
    """Убрать английское множественное ``-s`` у длинных латинских токенов.

    Индекс и запрос нормализуются одинаково, поэтому пары
    ``grape/grapes``, ``dose/doses`` и ``sign/signs`` совпадают. Кириллица
    не трогается: русские окончания разбирает префиксное сравнение с
    глоссарием.
    """
    if (
        token.isascii()
        and len(token) >= 4
        and token.endswith("s")
        and not token.endswith(("ss", "is", "us"))
    ):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Разбить текст на нормализованные токены.

    >>> tokenize("Ксилитом отравилась собака, доза 1,5 г")
    ['ксилитом', 'отравилась', 'собака', 'доза', '1', '5', 'г']
    """
    return [
        _normalize_latin_plural(raw)
        for raw in TOKEN_PATTERN.findall(text.lower())
    ]


def _term_matches(token: str, key: str) -> bool:
    """Совпадает ли русский токен с основой глоссария."""
    if token == key:
        return True
    if len(key) < 4 or not token.startswith(key):
        return False
    return len(token) - len(key) <= 3


def expand_query_terms(
    tokens: Iterable[str],
    *,
    glossary: Mapping[str, tuple[str, ...]] = RU_EN_TERMS,
) -> list[str]:
    """Добавить к токенам запроса их английские эквиваленты.

    Исходные токены сохраняются: у пользователя может быть и английский
    запрос. Дубликаты убираются, чтобы один термин не считался дважды.
    """
    expanded = list(tokens)
    seen = set(expanded)
    for token in tokens:
        for key, translations in glossary.items():
            if not _term_matches(token, key):
                continue
            for translation in translations:
                for part in tokenize(translation):
                    if part not in seen:
                        seen.add(part)
                        expanded.append(part)
    return expanded


def _contains_cyrillic(token: str) -> bool:
    """Есть ли в токене кириллица."""
    return any("а" <= char <= "я" or char == "ё" for char in token)


def weight_query_terms(
    tokens: Iterable[str],
    *,
    glossary: Mapping[str, tuple[str, ...]] = RU_EN_TERMS,
    fallback_weight: float = DEFAULT_RU_FALLBACK_WEIGHT,
) -> list[tuple[str, float]]:
    """Собрать взвешенные термины запроса для BM25.

    Если для русских токенов нашёлся перевод, их вес понижается до
    ``fallback_weight``: англоязычные статьи MSD должны выигрывать у
    маленьких русских демо-файлов, которые совпадают буквально. Английский
    запрос не меняется (все веса 1.0).
    """
    token_list = list(tokens)
    weighted: dict[str, float] = {}
    for token in token_list:
        weighted[token] = weighted.get(token, 0.0) + 1.0

    translated = False
    for token in token_list:
        for key, translations in glossary.items():
            if not _term_matches(token, key):
                continue
            translated = True
            for translation in translations:
                for part in tokenize(translation):
                    weighted[part] = weighted.get(part, 0.0) + 1.0

    if translated:
        for term in list(weighted):
            if _contains_cyrillic(term):
                weighted[term] *= fallback_weight
    return list(weighted.items())


class BM25Index:
    """Okapi BM25 по фиксированному набору документов.

    Документы не хранятся: класс возвращает индексы и scores, а тексты
    остаются у вызывающего кода. Заголовок документа учитывается через
    повторение его токенов в мешке слов (``title_weight``).
    """

    def __init__(
        self,
        documents: Sequence[str],
        *,
        titles: Sequence[str] | None = None,
        title_weight: float = DEFAULT_TITLE_WEIGHT,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        russian_fallback_weight: float = DEFAULT_RU_FALLBACK_WEIGHT,
        glossary: Mapping[str, tuple[str, ...]] = RU_EN_TERMS,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 должен быть > 0")
        if not 0 <= b <= 1:
            raise ValueError("b должен быть в диапазоне [0, 1]")
        if not 0 <= russian_fallback_weight <= 1:
            raise ValueError("russian_fallback_weight должен быть в диапазоне [0, 1]")

        self._k1 = k1
        self._b = b
        self._russian_fallback_weight = russian_fallback_weight
        self._glossary = glossary
        self._term_freqs: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        document_freqs: Counter[str] = Counter()
        title_repeats = max(round(title_weight), 1)

        for index, document in enumerate(documents):
            tokens = tokenize(document)
            if titles is not None and index < len(titles):
                title_tokens = tokenize(titles[index])
                if title_tokens:
                    tokens = tokens + title_tokens * title_repeats
            freqs = Counter(tokens)
            self._term_freqs.append(freqs)
            self._doc_lengths.append(len(tokens))
            document_freqs.update(freqs.keys())

        self._document_count = len(documents)
        self._avg_length = (
            sum(self._doc_lengths) / self._document_count
            if self._document_count
            else 0.0
        )
        self._idf = {
            term: math.log(
                1 + (self._document_count - freq + 0.5) / (freq + 0.5)
            )
            for term, freq in document_freqs.items()
        }

    @property
    def size(self) -> int:
        """Сколько документов в индексе."""
        return self._document_count

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        expand: bool = True,
    ) -> list[tuple[int, float]]:
        """Вернуть ``(индекс документа, score)`` по убыванию score."""
        if not self._document_count:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        if expand:
            weighted_terms = weight_query_terms(
                terms,
                glossary=self._glossary,
                fallback_weight=self._russian_fallback_weight,
            )
        else:
            weighted_terms = [(term, 1.0) for term in terms]

        scores = [0.0] * self._document_count
        for term, term_weight in weighted_terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for index, freqs in enumerate(self._term_freqs):
                frequency = freqs.get(term)
                if not frequency:
                    continue
                length = self._doc_lengths[index]
                denominator = frequency + self._k1 * (
                    1 - self._b + self._b * length / self._avg_length
                )
                scores[index] += (
                    term_weight * idf * frequency * (self._k1 + 1) / denominator
                )

        ranked = [
            (index, score) for index, score in enumerate(scores) if score > 0
        ]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:limit] if limit is not None else ranked


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[int, float]]:
    """Слить несколько ранжирований через Reciprocal Rank Fusion.

    ``score = Σ weight_i / (k + rank_i)``, rank начинается с 1. Результат
    отсортирован по убыванию score; при равенстве — по индексу, чтобы
    порядок был детерминированным.

    Raises:
        ValueError: ``weights`` задан, но его длина не совпадает с числом
            ранжирований, либо ``k`` отрицательный.
    """
    if k < 0:
        raise ValueError("k должен быть >= 0")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights должен совпадать по длине с rankings")

    effective_weights = list(weights) if weights is not None else [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, effective_weights, strict=True):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)

    fused = list(scores.items())
    fused.sort(key=lambda item: (-item[1], item[0]))
    return fused
