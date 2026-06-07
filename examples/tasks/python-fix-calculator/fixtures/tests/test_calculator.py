import unittest

from calculator import add, average, multiply


class CalculatorTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_multiply_handles_negative_left_operand(self):
        self.assertEqual(multiply(-3, 4), -12)

    def test_multiply_handles_negative_right_operand(self):
        self.assertEqual(multiply(3, -4), -12)

    def test_average_preserves_fractional_result(self):
        self.assertEqual(average([1, 2]), 1.5)


if __name__ == "__main__":
    unittest.main()
