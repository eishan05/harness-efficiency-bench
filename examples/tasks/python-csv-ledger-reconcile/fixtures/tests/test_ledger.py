import unittest

from ledger import reconcile_accounts


class LedgerTest(unittest.TestCase):
    def test_refunds_and_voids_are_handled(self):
        csv_text = """account,type,amount,void
cash,sale,10.00,false
cash,refund,2.50,false
cash,sale,99.99,true
fees,sale,0.10,false
fees,sale,0.20,false
"""

        self.assertEqual(reconcile_accounts(csv_text), {"cash": "7.50", "fees": "0.30"})

    def test_refund_amount_sign_is_normalized(self):
        csv_text = """account,type,amount,void
cash,sale,10.00,false
cash,refund,-1.25,false
"""

        self.assertEqual(reconcile_accounts(csv_text), {"cash": "8.75"})


if __name__ == "__main__":
    unittest.main()
