"""Datenklasse für ein gefundenes Angebot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Mögliche Status eines Angebots
OK = "ok"
VERDAECHTIG = "verdaechtig"
AUSGESCHLOSSEN = "ausgeschlossen"
NICHT_PASSEND = "nicht_passend"
NICHT_VERFUEGBAR = "nicht_verfuegbar"
ABGELAUFEN = "abgelaufen"      # Deal laut Quelle abgelaufen
IGNORIERT = "ignoriert"        # von dir ausgeblendet (data/ignoriert.json)


@dataclass
class Offer:
    product_id: str
    source: str              # Name der Datenquelle (mydealz, ebay, ...)
    shop: str                # Händler / Shop
    title: str
    url: str
    price: float | None      # Artikelpreis bzw. Leasing-Monatsrate
    shipping: float | None = None   # Versandkosten; None = unbekannt, 0 = frei
    hints: list[str] = field(default_factory=list)
    leasing: dict = field(default_factory=dict)  # rate, monate, km, sonderzahlung, bereitstellung, gewerbe
    status: str = OK
    status_reason: str = ""
    first_seen: str = ""
    last_seen: str = ""
    weitere_quellen: list[str] = field(default_factory=list)  # gleiches Angebot auch hier gefunden
    ean: str = ""            # EAN/GTIN laut Shopseite (falls angegeben)
    abzuege: list[dict] = field(default_factory=list)  # {art, betrag, text}: Gutschein, Cashback, Zahlart
    vertrauen: list[str] = field(default_factory=list)  # Warnungen der Vertrauensprüfung (gelb markiert)
    # Nur für die Auswertung (Beschreibungstext), wird nicht gespeichert
    text: str = field(default="", repr=False)

    @property
    def key(self) -> str:
        """Eindeutiger Schlüssel des Angebots (Shop + Link)."""
        return f"{self.shop.lower()}|{self.url.split('#')[0]}"

    @property
    def effective_rate(self) -> float | None:
        """Leasing: (Rate × Monate + Sonderzahlung + Bereitstellung) / Monate."""
        if self.price is None:
            return None
        months = self.leasing.get("monate")
        if not months:
            return None
        extra = (self.leasing.get("sonderzahlung") or 0) + (self.leasing.get("bereitstellung") or 0)
        return round((self.price * months + extra) / months, 2)

    @property
    def compare_price(self) -> float | None:
        """Preis, der verglichen wird: inkl. Versand bzw. effektive Leasingrate."""
        if self.price is None:
            return None
        if self.leasing:
            eff = self.effective_rate
            return eff if eff is not None else self.price
        # Effektivpreis: Preis + Versand − Gutschein − Cashback − Zahlungsrabatt
        return round(self.price + (self.shipping or 0) - sum(a["betrag"] for a in self.abzuege), 2)

    @property
    def target_value(self) -> float | None:
        """Wert, der mit dem Zielpreis verglichen wird (Leasing: Monatsrate)."""
        if self.leasing:
            return self.price
        return self.compare_price

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("text", None)
        d["vergleichspreis"] = self.compare_price
        if self.leasing:
            d["leasing"]["effektiv"] = self.effective_rate
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Offer":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k != "text"}
        o = cls(**known)
        if o.leasing:
            o.leasing = {k: v for k, v in o.leasing.items() if k != "effektiv"}
        return o
