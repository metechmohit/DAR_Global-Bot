import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional semantic packages are not installed')
class SemanticScoresTests(unittest.TestCase):
    def test_normalized_vectors_return_finite_bounded_scores(self):
        import numpy as np
        from app.semantic import similarity_scores
        vectors=np.array([[1,0],[0,1],[-1,0]],dtype=np.float32)
        with np.errstate(all='raise'):
            scores=similarity_scores(vectors,np.array([1,0],dtype=np.float32))
        np.testing.assert_allclose(scores,[1,0,-1])

    def test_invalid_dimensions_and_query_values_are_rejected(self):
        import numpy as np
        from app.semantic import similarity_scores
        with self.assertRaises(RuntimeError):similarity_scores(np.zeros((3,4)),np.zeros(2))
        with self.assertRaises(RuntimeError):similarity_scores(np.zeros((3,2)),np.array([float('nan'),0]))


if __name__=='__main__':unittest.main()
