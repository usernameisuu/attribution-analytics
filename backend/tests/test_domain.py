import unittest
from decimal import Decimal as D
from app.domain.attribution import additive, multiplicative, ratio_slices, shapley, number
from app.domain.scenarios import calculate, simulate


class AttributionTests(unittest.TestCase):
    def assert_conserved(self, result):
        self.assertLess(abs(result.delta-sum((x.contribution for x in result.factors), D(0))), D("1e-15"))

    def test_gmv_fixture(self):
        data = calculate("ecommerce")["breakdown"]
        self.assertEqual(D(data["delta"]), -352000)
        self.assertLess(abs(D(data["residual"])), D("1e-15"))
        self.assertGreater(D(data["factors"][0]["contribution"]), 0)
        self.assertEqual(data["factors"][0]["label"], "访问次数")

    def test_profit_fixture(self):
        data = calculate("consumer")
        self.assertEqual(D(data["breakdown"]["delta"]), -107000)
        self.assertAlmostEqual(float(data["margin_breakdown"]["delta"]), -9.94736842105263)

    def test_equal_total_retains_offsetting_contributions(self):
        result = multiplicative({"a":1,"b":4},{"a":2,"b":2},{})
        self.assert_conserved(result)
        self.assertNotEqual(result.factors[0].contribution, 0)
        self.assertIsNone(result.as_dict()["factors"][0]["contribution_rate"])

    def test_small_nonzero_change_has_a_contribution_rate(self):
        result = additive({'a': '1', 'b': '1'},
                          {'a': '1.000000000000000000000000000000000001', 'b': '1'},
                          {'a': 1, 'b': 1}, {})
        values = result.as_dict()
        self.assertEqual(D(values['delta']), D('1e-36'))
        self.assertEqual(D(values['factors'][0]['contribution_rate']), D(1))
        self.assertEqual(D(values['factors'][1]['contribution_rate']), D(0))

    def test_zero_and_negative_fallback(self):
        for base,current in [({"a":0,"b":2},{"a":4,"b":3}),({"a":-2,"b":3},{"a":4,"b":5})]:
            result = multiplicative(base,current,{})
            self.assertIn("not_applicable", result.method)
            self.assert_conserved(result)

    def test_nearly_equal_values(self):
        self.assert_conserved(multiplicative({"a":"1.000000000001","b":10},{"a":"1.000000000002","b":10},{}))

    def test_twelve_slice_ratio(self):
        base = {str(i):(i+1,100+i) for i in range(12)}
        current = {str(i):(i+2,102+i) for i in range(12)}
        self.assert_conserved(ratio_slices(base,current,{}))

    def test_invalid_counterfactual(self):
        with self.assertRaises(ValueError):
            shapley({"a":1,"b":0},{"a":2,"b":1},lambda x:x["a"]/x["b"],{})

    def test_non_finite_rejected(self):
        for value in ("NaN","Infinity","-Infinity","bad"):
            with self.assertRaises(ValueError): number(value)

    def test_simulations(self):
        self.assertEqual(D(simulate("ecommerce",{"conversion":"0.035"})["improvement"]),108000)
        self.assertEqual(D(simulate("consumer",{"material":"513000"})["prediction"]),170000)
        with self.assertRaises(ValueError): simulate("ecommerce",{"conversion":"1.5"})

    def test_mismatched_input(self):
        with self.assertRaises(ValueError): multiplicative({"a":1},{"b":2},{})


if __name__ == "__main__":
    unittest.main()
