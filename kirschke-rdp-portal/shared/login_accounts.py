"""Names of existing Windows accounts; never passwords or AD access grants."""


def validate_login_account(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Bitte einen Kontonamen eingeben.")
    if any(ord(char) < 32 or char in "\x7f\x85\u2028\u2029" for char in value):
        raise ValueError("Der Kontoname darf keine Steuerzeichen enthalten.")
    value = value.strip()
    if not value or len(value) > 256:
        raise ValueError("Der Kontoname muss 1 bis 256 Zeichen enthalten.")
    if any(char in value for char in '/"[]:;|=,*?<>'):
        raise ValueError("Ungültiger Kontoname. Beispiel: ZIELPC\\benutzer oder benutzer@firma.de")
    if value.count("\\") > 1 or value.startswith("\\") or value.endswith("\\"):
        raise ValueError("Bitte das Format ZIELPC\\benutzer verwenden.")
    return value


def normalize_login_accounts(values: list[str]) -> list[str]:
    unique = {}
    for value in values:
        account = validate_login_account(value)
        unique.setdefault(account.casefold(), account)
    return list(unique.values())
