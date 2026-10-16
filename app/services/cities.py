"""Cities / districts of Tamil Nadu that people pick at registration.

All 38 districts are listed here; only those in ENABLED_CITIES (settings) are offered and accepted.
To start serving a new district, add its slug to ENABLED_CITIES — no code change needed.
The order of ENABLED_CITIES is the order shown to people.
"""

from app.core.config import get_settings

# slug: (English, Tamil)
DISTRICTS: dict[str, tuple[str, str]] = {
    "ariyalur": ("Ariyalur", "அரியலூர்"),
    "chengalpattu": ("Chengalpattu", "செங்கல்பட்டு"),
    "chennai": ("Chennai", "சென்னை"),
    "coimbatore": ("Coimbatore", "கோயம்புத்தூர்"),
    "cuddalore": ("Cuddalore", "கடலூர்"),
    "dharmapuri": ("Dharmapuri", "தருமபுரி"),
    "dindigul": ("Dindigul", "திண்டுக்கல்"),
    "erode": ("Erode", "ஈரோடு"),
    "kallakurichi": ("Kallakurichi", "கள்ளக்குறிச்சி"),
    "kancheepuram": ("Kancheepuram", "காஞ்சிபுரம்"),
    "kanniyakumari": ("Kanniyakumari", "கன்னியாகுமரி"),
    "karur": ("Karur", "கரூர்"),
    "krishnagiri": ("Krishnagiri", "கிருஷ்ணகிரி"),
    "madurai": ("Madurai", "மதுரை"),
    "mayiladuthurai": ("Mayiladuthurai", "மயிலாடுதுறை"),
    "nagapattinam": ("Nagapattinam", "நாகப்பட்டினம்"),
    "namakkal": ("Namakkal", "நாமக்கல்"),
    "nilgiris": ("Nilgiris", "நீலகிரி"),
    "perambalur": ("Perambalur", "பெரம்பலூர்"),
    "pudukkottai": ("Pudukkottai", "புதுக்கோட்டை"),
    "ramanathapuram": ("Ramanathapuram", "இராமநாதபுரம்"),
    "ranipet": ("Ranipet", "இராணிப்பேட்டை"),
    "salem": ("Salem", "சேலம்"),
    "sivaganga": ("Sivaganga", "சிவகங்கை"),
    "tenkasi": ("Tenkasi", "தென்காசி"),
    "thanjavur": ("Thanjavur", "தஞ்சாவூர்"),
    "theni": ("Theni", "தேனி"),
    "thoothukudi": ("Thoothukudi", "தூத்துக்குடி"),
    "tiruchirappalli": ("Tiruchirappalli (Trichy)", "திருச்சிராப்பள்ளி (திருச்சி)"),
    "tirunelveli": ("Tirunelveli", "திருநெல்வேலி"),
    "tirupathur": ("Tirupathur", "திருப்பத்தூர்"),
    "tiruppur": ("Tiruppur", "திருப்பூர்"),
    "tiruvallur": ("Tiruvallur", "திருவள்ளூர்"),
    "tiruvannamalai": ("Tiruvannamalai", "திருவண்ணாமலை"),
    "tiruvarur": ("Tiruvarur", "திருவாரூர்"),
    "vellore": ("Vellore", "வேலூர்"),
    "viluppuram": ("Viluppuram", "விழுப்புரம்"),
    "virudhunagar": ("Virudhunagar", "விருதுநகர்"),
}


def enabled() -> list[str]:
    slugs = [s.strip().lower() for s in get_settings().enabled_cities.split(",") if s.strip()]
    return [s for s in slugs if s in DISTRICTS]


def check(slug: str) -> str:
    """Normalise a city slug; ValueError if it isn't one we serve yet."""
    s = slug.strip().lower()
    if s not in enabled():
        names = ", ".join(DISTRICTS[c][0] for c in enabled())
        raise ValueError(f"We don't serve this city yet. Choose one of: {names}")
    return s
