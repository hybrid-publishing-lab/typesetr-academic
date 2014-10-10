# pylint: disable=W0231
class Literal(object):
    """Abstract baseclass for literals."""
    def __eq__(self, other):
        return type(self) is type(other) and (
            self.to_string() == other.to_string()) # pylint: disable=E1101
    def __ne__(self, other):
        return not self == other
    def to_string(self):
        return NotImplemented
    @classmethod
    def from_string(cls, s): # pylint: disable=W0613
        return NotImplemented
