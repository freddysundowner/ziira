"""What counts as an acceptable password: long enough, not one of the passwords everybody tries first, not the login."""

from ziira.kernel.errors import ValidationFailed

MIN_LENGTH = 8

# The passwords attackers try first (a short list: the point is to refuse the obvious, not to replace a manager).
COMMON = frozenset("""
password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword 12345678 123456789 1234567890 11111111
00000000 87654321 qwertyui qwerty123 qwertyuiop 1q2w3e4r 1q2w3e4r5t q1w2e3r4 qazwsxedc abc12345 abcd1234 abcdefgh
iloveyou letmein welcome welcome1 welcome123 admin123 administrator changeme changeme123 default123 test1234 testtest
monkey123 dragon123 football1 baseball1 superman1 sunshine1 princess1 trustno1 starwars1 master123 login123 secret123
zxcvbnm1 asdfghjk asdf1234 qwer1234 12341234 123123123 111222333 a1b2c3d4 passpass pass1234 ziira123 ziira1234
""".split())  # noqa: SIM905


def check(password: str, *, login: str | None = None) -> None:
    """Raise ValidationFailed with a plain reason if the password is not acceptable."""
    if len(password) < MIN_LENGTH:
        raise ValidationFailed(f"Password must be at least {MIN_LENGTH} characters")
    lowered = password.lower()
    if lowered in COMMON or len(set(lowered)) <= 2:
        raise ValidationFailed("That password is too easy to guess: choose something less common")
    if login:
        name = login.strip().lower()
        local = name.split("@")[0]
        if lowered == name or (len(local) >= 4 and lowered == local):
            raise ValidationFailed("The password cannot be your login")
