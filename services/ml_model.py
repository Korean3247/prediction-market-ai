"""
XGBoost-based probability calibration model.
Trains on historical prediction outcomes and refines LLM predictions.
Falls back to LLM-only if insufficient training data (<20 samples).
"""
import logging
import pickle
import os
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)
MODEL_PATH = "ml_model.pkl"
MIN_TRAINING_SAMPLES = 20

class ProbabilityCalibrator:
    def __init__(self):
        self.model = None
        self.is_trained = False
        self._load()

    def _features(self, market_price: float, llm_prob: float,
                  sentiment: float, credibility: float,
                  liquidity: float, volume: float, spread: float) -> np.ndarray:
        """Extract features for the model."""
        return np.array([[
            market_price,
            llm_prob,
            abs(llm_prob - market_price),  # disagreement
            sentiment,
            credibility,
            min(1.0, liquidity / 100000),  # normalized
            min(1.0, volume / 10000),
            spread,
            market_price * (1 - market_price),  # variance proxy
        ]])

    def predict(self, market_price: float, llm_prob: float,
                sentiment: float, credibility: float,
                liquidity: float, volume: float, spread: float) -> Tuple[float, float]:
        """
        Returns (calibrated_probability, confidence_boost).
        Falls back to llm_prob if model not trained.
        """
        if not self.is_trained:
            return llm_prob, 0.0
        try:
            X = self._features(market_price, llm_prob, sentiment, credibility, liquidity, volume, spread)
            pred = float(self.model.predict_proba(X)[0][1])
            pred = max(0.01, min(0.99, pred))
            confidence_boost = 0.1 if abs(pred - llm_prob) < 0.05 else 0.0
            return pred, confidence_boost
        except Exception as e:
            logger.error(f"ML prediction failed: {e}")
            return llm_prob, 0.0

    def train(self, outcomes_data: list) -> bool:
        """
        Train on list of dicts: {market_price, llm_prob, sentiment, credibility,
                                  liquidity, volume, spread, actual_result}
        Returns True if training succeeded.
        """
        if len(outcomes_data) < MIN_TRAINING_SAMPLES:
            logger.info(f"Insufficient data for ML training: {len(outcomes_data)} < {MIN_TRAINING_SAMPLES}")
            return False
        try:
            from xgboost import XGBClassifier
            X = np.vstack([
                self._features(d['market_price'], d['llm_prob'], d['sentiment'],
                               d['credibility'], d['liquidity'], d['volume'], d['spread'])
                for d in outcomes_data
            ])
            y = np.array([int(d['actual_result']) for d in outcomes_data])
            self.model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1,
                                        use_label_encoder=False, eval_metric='logloss')
            self.model.fit(X, y)
            self.is_trained = True
            self._save()
            logger.info(f"ML model trained on {len(outcomes_data)} samples.")
            return True
        except Exception as e:
            logger.error(f"ML training failed: {e}")
            return False

    def _save(self):
        try:
            with open(MODEL_PATH, 'wb') as f:
                pickle.dump(self.model, f)
        except Exception as e:
            logger.error(f"Failed to save ML model: {e}")

    def _load(self):
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, 'rb') as f:
                    self.model = pickle.load(f)
                self.is_trained = True
                logger.info("ML model loaded from disk.")
            except Exception as e:
                logger.error(f"Failed to load ML model: {e}")

calibrator = ProbabilityCalibrator()
