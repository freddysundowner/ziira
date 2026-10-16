"""Seed SAMPLE plans, prices and an add-on into the master database (development only; idempotent).

The prices are placeholders to try the Super Admin and the pricing page. Replace them in the Super Admin before any
real use. Run: set -a; . ./.env; set +a; .venv/bin/python scripts/seed_sample_plans.py
"""

from ziira.kernel.errors import Conflict
from ziira.kernel.platform import plans, settings

SAMPLE = [
    {"code": "starter", "name": "Starter", "edition": "retail", "max_users": 3, "max_branches": 1, "max_companies": 1,
     "trial_days": 14, "sort_order": 10, "is_public": True, "intervals": ["month", "year"],
     "description": "Sell, keep stock and see how the day went. For one shop.",
     "highlights": ["Till, stock and customers", "Daily check on cash and stock", "1 branch, up to 3 users"],
     "prices": {"month": "29", "year": "290"},
     "prices_kes": {"month": "3500", "year": "35000"}},
    {"code": "growth", "name": "Growth", "edition": "distribution", "max_users": 15, "max_branches": 5,
     "max_companies": 1, "trial_days": 14, "sort_order": 20, "is_public": True, "intervals": ["month", "year"],
     "description": "Buying, selling on credit and books for businesses with several branches.",
     "highlights": ["Purchasing and supplier bills", "Customer credit and reminders", "Accounting and reports",
                    "Up to 5 branches, 15 users"],
     "prices": {"month": "79", "year": "790"},
     "prices_kes": {"month": "9900", "year": "99000"}},
    {"code": "business", "name": "Business", "edition": "full", "max_users": 60, "max_branches": 20,
     "max_companies": 5, "trial_days": 14, "sort_order": 30, "is_public": True, "intervals": ["month", "year"],
     "description": "The whole system: sales, stock, money, people and the daily check.",
     "highlights": ["Everything in Growth", "People and payroll", "Several companies in one view",
                    "Up to 20 branches, 60 users"],
     "prices": {"month": "199", "year": "1990"},
     "prices_kes": {"month": "24900", "year": "249000"}},
    {"code": "watch", "name": "Watch", "edition": "intelligence", "max_users": 10, "max_branches": 10,
     "max_companies": 1, "trial_days": 14, "sort_order": 40, "is_public": True, "intervals": ["month", "year"],
     "description": "Keep your current system. Ziira checks it every day and tells you what looks wrong.",
     "highlights": ["Connect your ERP or upload statements", "Daily brief and alerts", "Read only, nothing changes"],
     "prices": {"month": "49", "year": "490"},
     "prices_kes": {"month": "5900", "year": "59000"}},
]


def main() -> None:
    for sample in SAMPLE:
        data = {k: v for k, v in sample.items() if k not in ("prices", "prices_kes")}
        try:
            plan = plans.create_plan(data)
            print(f"created plan {plan['code']}")
        except Conflict:
            plan = plans.get_plan(sample["code"])
            print(f"plan {plan['code']} exists")
        # SAMPLE prices only. The KES ones let the M-Pesa payment flow be tried; set real prices in the Super Admin.
        for currency, prices in (("USD", sample["prices"]), ("KES", sample["prices_kes"])):
            for interval, amount in prices.items():
                try:
                    plans.set_price("plan", plan["id"], currency=currency, interval=interval, amount=amount,
                                    tax_inclusive=False, by="seed_sample_plans")
                    print(f"  price {currency} {amount}/{interval}")
                except Exception as problem:  # a price already set: keep it
                    print(f"  price {currency} {interval}: {problem}")
    plans.invalidate_public_cache()
    settings.set_value("billing.default_plan_code", "starter", "seed_sample_plans")
    print("default plan for new sign-ups: starter")
    print("done")


if __name__ == "__main__":
    main()
