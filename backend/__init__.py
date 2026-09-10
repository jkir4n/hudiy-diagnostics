"""Hudiy Diagnostics backend package.

The importable units live in :mod:`backend.diag`. Keeping ``backend`` a real
package (rather than a namespace) is what lets ``python3 -m unittest discover
-s backend -t .`` resolve ``backend.tests.*`` from the repository root.
"""
