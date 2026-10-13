"""Public interface of the Finance and Accounting module.

Other units do not call Finance: they publish documents (`sale.posted`, `sale.returned`, and the stock movements
Inventory already publishes) and Finance turns them into journal entries. Nothing is exposed here yet.
"""
