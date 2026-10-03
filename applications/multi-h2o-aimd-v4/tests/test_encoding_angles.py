import math
import unittest
from water10_v4.encoding_angles import enforce_encoding_floor


class EncodingAngleFloor(unittest.TestCase):
    def test_sign_zero_and_boundaries(self):
        for value,expected in [(-7.497803663773237e-5,-.1),(.0009680800134292542,.1),
                               (0.,.1),(-0.,.1),(-.1,-.1),(.1,.1),(-1.2,-1.2),(1.2,1.2)]:
            self.assertEqual(enforce_encoding_floor(value),expected)

    def test_invalid_inputs(self):
        for value in (math.nan,math.inf,-math.inf):
            with self.assertRaises(ValueError): enforce_encoding_floor(value)
        for floor in (0.,-.1,math.nan,math.inf):
            with self.assertRaises(ValueError): enforce_encoding_floor(.2,floor)


if __name__=='__main__': unittest.main()
