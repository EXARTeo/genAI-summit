"""Business logic and DB queries, one module per domain.

No re-exports: import from the module that owns a name
(``from utils.conversations import init_conv``). A barrel here pulled every
domain into every import and hid cycles.
"""
