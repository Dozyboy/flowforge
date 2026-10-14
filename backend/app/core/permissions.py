from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def level(self) -> int:
        return _ROLE_LEVELS[self]

    def at_least(self, required: "Role") -> bool:
        return self.level >= required.level


_ROLE_LEVELS = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}
