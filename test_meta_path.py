import sys
import importlib.metadata

class MockDistribution(importlib.metadata.Distribution):
    def read_text(self, filename):
        if filename == 'METADATA':
            return "Metadata-Version: 2.1\nName: email-validator\nVersion: 2.1.0\n"
        return None
    def locate_file(self, path):
        return path

class MockFinder:
    def find_distributions(self, context=None):
        if context and context.name == "email-validator":
            yield MockDistribution()
        elif context and context.name == "email_validator":
            yield MockDistribution()

sys.meta_path.insert(0, MockFinder())

# Test if it works
print(importlib.metadata.version('email-validator'))
