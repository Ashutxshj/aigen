"""The strictly-one-line outreach message for each lead.

No LLM: the pitch is a deterministic template personalized with the business
name, its Google Maps social proof, and a niche-specific benefit word. One line
means ONE line — no newlines ever — sized to paste straight into WhatsApp.
"""

import re

# What the website/marketing actually brings each niche. Falls back to
# "customers" for anything unmapped. Keys are matched as substrings of the
# selected niche, so "restaurants" and "north indian restaurants" both hit.
_BENEFIT = {
    "restaurant": "diners",
    "cafe": "regulars",
    "bakeries": "orders",
    "cloud kitchen": "orders",
    "sweet": "orders",
    "dentist": "patients",
    "doctor": "patients",
    "clinic": "patients",
    "physio": "patients",
    "lab": "bookings",
    "salon": "bookings",
    "spa": "bookings",
    "gym": "members",
    "yoga": "students",
    "coaching": "admissions",
    "tutor": "students",
    "school": "admissions",
    "academ": "students",
    "class": "students",
    "photograph": "shoots",
    "planner": "events",
    "caterer": "events",
    "banquet": "bookings",
    "interior": "projects",
    "architect": "projects",
    "real estate": "buyers",
    "travel": "bookings",
    "garage": "service visits",
    "car wash": "bookings",
    "boutique": "shoppers",
    "jewel": "shoppers",
    "store": "shoppers",
    "shop": "shoppers",
    "florist": "orders",
    "tailor": "orders",
    "dry clean": "orders",
    "movers": "enquiries",
    "printing": "orders",
    "accountant": "clients",
    "lawyer": "clients",
    "insurance": "clients",
}


def _benefit(niche: str, category: str) -> str:
    hay = f"{niche} {category}".lower()
    for key, word in _BENEFIT.items():
        if key in hay:
            return word
    return "customers"


def _short_name(business_name: str) -> str:
    """First few words of the name, so the greeting reads like a human wrote it
    ('Hi Spice Route team' not 'Hi Spice Route Family Restaurant Pvt Ltd team')."""
    name = re.sub(r"\s+", " ", business_name).strip()
    words = name.split(" ")
    return " ".join(words[:3])


def one_liner(target: dict, niche: str) -> str:
    """The message. Strictly one line, personalized, ready to send as-is."""
    name = _short_name(target.get("business_name", "")) or "there"
    benefit = _benefit(niche, target.get("category", ""))
    rating = target.get("rating")
    reviews = target.get("reviews") or 0

    if rating and reviews >= 50:
        proof = (f"your {rating:g}-star rating and {reviews}+ reviews on Google "
                 f"show people already love you, but without a website you're "
                 f"invisible to everyone searching online")
    elif rating:
        proof = (f"you have a solid {rating:g}-star presence on Google Maps but "
                 f"no website, so online searches are passing you by")
    else:
        proof = ("you're on Google Maps but have no website, so people searching "
                 "online never find you")

    # No em dashes anywhere in outgoing text: they read as machine-written.
    msg = (f"Hi {name} team, {proof}. I run a digital marketing agency and can "
           f"get you a website plus Google visibility that brings in more "
           f"{benefit}; open to a quick 10-minute chat this week?")
    return " ".join(msg.split())   # guarantee: exactly one line, single-spaced
