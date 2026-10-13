import json


class RegisterWrite:

    def __init__(self, register, value):
        self._i = register
        self._v = value

    def dict(self):
        # WriteDataItems takes the value as a String: strings as they are,
        # anything else as JSON (true/false, numbers, {"hour": .., "minute": ..}),
        # as the SaveConnect app sends it.
        value = self._v if isinstance(self._v, str) else json.dumps(self._v)
        return {
            "id": self._i,
            "value": value
        }
