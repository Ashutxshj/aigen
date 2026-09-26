"""The strictly-one-line outreach message for each lead.

No LLM: the pitch is a deterministic template personalized with the business
name, the age of its own domain (the whole hook of this tool), its Google Maps
social proof, and a category-specific benefit word. One line means ONE line —
no newlines ever — sized to paste straight into an email or contact form.
"""

import re

# What a modern website actually brings each category. Falls back to
# "customers" for anything unmapped. Keys are matched as substrings of the
# category, so "Law firm" and "Personal injury law firm" both hit.
_BENEFIT = {
    "law": "clients",
    "attorney": "clients",
    "account": "clients",
    "tax": "clients",
    "insurance": "policy enquiries",
    "real estate": "listings and buyers",
    "dent": "patients",
    "clinic": "patients",
    "doctor": "patients",
    "chiropract": "patients",
    "optometr": "appointments",
    "veterinar": "appointments",
    "restaurant": "diners",
    "diner": "diners",
    "cafe": "regulars",
    "auto": "repair jobs",
    "tire": "repair jobs",
    "tow": "calls",
    "plumb": "service calls",
    "hvac": "service calls",
    "heating": "service calls",
    "electric": "service calls",
    "roof": "estimates",
    "landscap": "estimates",
    "pest": "bookings",
    "moving": "bookings",
    "storage": "bookings",
    "funeral": "families served",
    "travel": "bookings",
    "print": "orders",
    "clean": "orders",
    "furniture": "shoppers",
    "store": "shoppers",
}


def _benefit(category: str) -> str:
    hay = (category or "").lower()
    for key, word in _BENEFIT.items():
        if key in hay:
            return word
    return "customers"


def _short_name(business_name: str) -> str:
    """First few words of the name, so the greeting reads like a human wrote it
    ('Hi Hendricks & Sons team' not 'Hi Hendricks & Sons Law Office LLC team')."""
    name = re.sub(r"\s+", " ", business_name).strip()
    words = name.split(" ")
    return " ".join(words[:3])


def one_liner(target: dict, registered, age: float) -> str:
    """The message. Strictly one line, personalized, ready to send as-is."""
    name = _short_name(target.get("business_name", "")) or "there"
    domain = target.get("domain", "your website")
    benefit = _benefit(target.get("category", ""))
    rating = target.get("rating")
    reviews = target.get("reviews") or 0
    years = int(age)

    if rating and reviews >= 50:
        proof = (f"your {rating:g}-star rating and {reviews}+ Google reviews show "
                 f"the business has never been stronger, but {domain} has been "
                 f"online since {registered.year}, about {years} years, and next "
                 f"to newer competitors it is starting to cost you trust")
    else:
        proof = (f"{domain} has been online since {registered.year}, about "
                 f"{years} years, and sites from that era quietly turn away "
                 f"people who look you up on their phones today")

    # No em dashes anywhere in outgoing text: they read as machine-written.
    msg = (f"Hi {name} team, {proof}. I run a web design studio and can rebuild "
           f"it into a fast, modern site that brings in more {benefit}; open to "
           f"a quick 10 minute chat this week?")
    return " ".join(msg.split())   # guarantee: exactly one line, single-spaced
