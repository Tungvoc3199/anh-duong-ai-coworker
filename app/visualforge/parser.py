from __future__ import annotations

import re
import unicodedata

from app.visualforge.models import VisualPromptSpec


class VisualPromptParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisualPromptParser:
    _TEXT_PATTERN = re.compile(
        r'(?:required\s*text|text(?:\s+(?:hi[eể]n\s+th[iị]\s+)?ch[ií]nh\s+x[aá]c)?|headline|ch[uữ]|n[oộ]i\s+dung|copy|visible\s+text|exact\s+copy)'
        r'\s*[:\-]?\s*["“](.+?)["”]',
        re.IGNORECASE,
    )
    _TEXT_LABEL_PATTERN = re.compile(
        r'(?:required\s*text|text(?:\s+(?:hi[eể]n\s+th[iị]\s+)?ch[ií]nh\s+x[aá]c)?|headline|ch[uữ]|n[oộ]i\s+dung|copy|visible\s+text|exact\s+copy)',
        re.IGNORECASE,
    )
    _ASPECT_PATTERN = re.compile(r'(?<!\d)(1:1|4:5|5:4|9:16|16:9|3:4|4:3)(?!\d)')
    _QUOTED_PATTERN = re.compile(r'["“](.+?)["”]')

    def parse(self, goal: str) -> VisualPromptSpec:
        normalized = self._normalize(goal)
        template = self._template(normalized)
        required_match = self._TEXT_PATTERN.search(goal)
        label_match = self._TEXT_LABEL_PATTERN.search(goal)
        quoted_values = self._QUOTED_PATTERN.findall(goal)
        if required_match:
            required_text = required_match.group(1)
        elif label_match:
            raise VisualPromptParseError(
                "visualforge_visible_text_unquoted",
                "Visible text labels require quoted exact copy.",
            )
        elif len(quoted_values) == 1:
            required_text = quoted_values[0]
        elif len(quoted_values) > 1:
            raise VisualPromptParseError(
                "visualforge_visible_text_ambiguous",
                "Multiple quoted values were found without a visible-text label.",
            )
        else:
            required_text = ""
        aspect_match = self._ASPECT_PATTERN.search(goal)
        return VisualPromptSpec(
            query=self._query(template, normalized),
            brief=goal.strip(),
            template=template,
            adapter="gpt-image",
            required_text=required_text,
            aspect_ratio=(aspect_match.group(1) if aspect_match else ""),
        )

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        plain = "".join(
            char for char in decomposed if not unicodedata.combining(char)
        ).replace("đ", "d")
        return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())

    @classmethod
    def _template(cls, text: str) -> str:
        if "tiktok" in text or "affiliate" in text:
            return "tiktok-affiliate-hook"
        if "tet" in text:
            return "vietnamese-local-tet-sale"
        if "ca phe" in text or "cafe" in text:
            return "vietnamese-local-cafe"
        if any(item in text for item in ("serum", "skincare", "beauty", "my pham")):
            return "beauty-skincare-launch"
        if "streetwear" in text:
            return "fashion-streetwear-drop"
        if "fashion" in text or "thoi trang" in text:
            return "fashion-lookbook"
        if "infographic" in text:
            return "infographic-data-story"
        if "poster" in text or "su kien" in text:
            return "poster-event-promo"
        if any(item in text for item in ("menu", "food", "do an")):
            return "food-delivery-menu"
        if "restaurant" in text or "nha hang" in text:
            return "restaurant-hero-banner"
        if any(item in text for item in ("marketplace", "thumbnail", "shopee", "lazada")):
            return "product-marketplace-thumbnail"
        return "ecommerce-product-hero"

    @staticmethod
    def _query(template: str, text: str) -> str:
        queries = {
            "tiktok-affiliate-hook": "product ecommerce",
            "beauty-skincare-launch": "beauty skincare",
            "fashion-lookbook": "fashion",
            "fashion-streetwear-drop": "fashion streetwear",
            "food-delivery-menu": "food",
            "restaurant-hero-banner": "food restaurant",
            "poster-event-promo": "poster",
            "infographic-data-story": "infographic",
            "product-marketplace-thumbnail": "product ecommerce",
            "vietnamese-local-cafe": "food vietnamese local",
            "vietnamese-local-tet-sale": "product vietnamese local",
            "ecommerce-product-hero": "product ecommerce",
        }
        if template == "tiktok-affiliate-hook":
            if any(item in text for item in ("serum", "skincare", "beauty", "my pham")):
                return "beauty ecommerce serum skincare"
            if any(item in text for item in ("food", "do an", "ca phe", "cafe", "coffee")):
                return "food ecommerce social media"
            if any(item in text for item in ("fashion", "thoi trang", "streetwear")):
                return "fashion ecommerce social media"
            return "product ecommerce social media"
        return queries[template]
