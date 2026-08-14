"""Client UI subpackage.

PySide6 imports are deferred to runtime entry points so that importing this
package does not require Qt to be installed. The CPU test suite must not import
the modules that pull in PySide6.
"""
