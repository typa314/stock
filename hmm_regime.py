# -*- coding: utf-8 -*-
"""
Lightweight, numerically stable 2-state / 3-state Gaussian HMM for market regime detection.
Zero external dependencies beyond numpy and scipy.
Strictly point-in-time forward filtering (zero lookahead bias).
"""
import numpy as np
try:
    from scipy.special import logsumexp
except ImportError:
    def logsumexp(a, axis=None, keepdims=False):
        """Pure NumPy numerically stable logsumexp fallback."""
        a = np.asarray(a)
        a_max = np.amax(a, axis=axis, keepdims=True)
        a_max_clean = np.where(np.isfinite(a_max), a_max, 0.0)
        tmp = np.exp(a - a_max_clean)
        s = np.sum(tmp, axis=axis, keepdims=keepdims)
        s_clean = np.where(s > 0, s, 1.0)
        out = np.where(s > 0, np.log(s_clean), -np.inf)
        if not keepdims:
            a_max_clean = np.squeeze(a_max_clean, axis=axis)
        out += a_max_clean
        return out

class GaussianHMM1D2D:
    def __init__(self, n_components=2, n_iter=30, tol=1e-4, random_state=42):
        self.n_components = n_components
        self.n_iter = n_iter
        self.tol = tol
        self.random_state = random_state
        self.pi = None      # (K,) Initial state probabilities
        self.A = None       # (K, K) Transition matrix
        self.means = None   # (K, D) Means
        self.covs = None    # (K, D) Covariances (diagonal)

    def _init_params(self, X):
        rng = np.random.RandomState(self.random_state)
        N, D = X.shape
        K = self.n_components
        self.pi = np.full(K, 1.0 / K)
        self.A = np.full((K, K), 0.1 / (K - 1))
        for i in range(K):
            self.A[i, i] = 0.9  # Sticky regimes
        # Initialize means via quantiles of first feature (usually returns)
        quantiles = np.linspace(0.2, 0.8, K)
        self.means = np.zeros((K, D))
        for k in range(K):
            idx = int(quantiles[k] * N)
            self.means[k] = np.sort(X, axis=0)[idx] + rng.randn(D) * 0.01
        self.covs = np.zeros((K, D))
        total_var = np.var(X, axis=0) + 1e-6
        for k in range(K):
            self.covs[k] = total_var * (1.0 + 0.5 * k)

    def _log_emission_prob(self, X):
        N, D = X.shape
        K = self.n_components
        log_B = np.zeros((N, K))
        for k in range(K):
            diff = X - self.means[k]  # (N, D)
            var = np.maximum(self.covs[k], 1e-6)
            log_det = np.sum(np.log(var))
            quad = np.sum((diff ** 2) / var, axis=1)
            log_B[:, k] = -0.5 * (D * np.log(2 * np.pi) + log_det + quad)
        return log_B

    def fit(self, X):
        X = np.asarray(X)
        if X.ndim == 1:
            X = X[:, np.newaxis]
        N, D = X.shape
        K = self.n_components
        self._init_params(X)

        prev_ll = -np.inf
        for it in range(self.n_iter):
            log_B = self._log_emission_prob(X)  # (N, K)
            log_pi = np.log(np.maximum(self.pi, 1e-12))
            log_A = np.log(np.maximum(self.A, 1e-12))

            # Forward pass (in log space)
            log_alpha = np.zeros((N, K))
            log_alpha[0] = log_pi + log_B[0]
            for t in range(1, N):
                for k in range(K):
                    log_alpha[t, k] = log_B[t, k] + logsumexp(log_alpha[t - 1] + log_A[:, k])

            ll = logsumexp(log_alpha[-1])
            if np.abs(ll - prev_ll) < self.tol:
                break
            prev_ll = ll

            # Backward pass (in log space)
            log_beta = np.zeros((N, K))
            log_beta[-1] = 0.0
            for t in range(N - 2, -1, -1):
                for i in range(K):
                    log_beta[t, i] = logsumexp(log_A[i, :] + log_B[t + 1, :] + log_beta[t + 1, :])

            # Posterior gamma: P(S_t = k | X_{1..N})
            log_gamma = log_alpha + log_beta
            log_gamma -= logsumexp(log_gamma, axis=1, keepdims=True)
            gamma = np.exp(log_gamma)

            # Posterior xi: P(S_t = i, S_{t+1} = j | X_{1..N})
            xi_sum = np.zeros((K, K))
            for t in range(N - 1):
                log_xi_t = log_alpha[t, :, np.newaxis] + log_A + log_B[t + 1, np.newaxis, :] + log_beta[t + 1, np.newaxis, :]
                log_xi_t -= logsumexp(log_xi_t)
                xi_sum += np.exp(log_xi_t)

            # M-step updates
            self.pi = gamma[0] / np.sum(gamma[0])
            self.A = xi_sum / np.maximum(np.sum(xi_sum, axis=1, keepdims=True), 1e-12)
            for k in range(K):
                w = gamma[:, k]
                w_sum = np.maximum(np.sum(w), 1e-12)
                self.means[k] = np.sum(w[:, np.newaxis] * X, axis=0) / w_sum
                diff = X - self.means[k]
                self.covs[k] = np.sum(w[:, np.newaxis] * (diff ** 2), axis=0) / w_sum + 1e-6

        self._sort_states()
        return self

    def _sort_states(self):
        # Sort states by volatility (cov on feature 0 or feature 1) so State 0 is Low-Vol, State K-1 is High-Vol
        # Or by mean return: State 0 = Bull (high mean, low vol), State 1 = Bear/Churn
        vol = np.mean(self.covs, axis=1)
        means = self.means[:, 0]
        # Score states: higher mean / sqrt(vol) is Bullish/Healthy
        sharpe = means / (np.sqrt(vol) + 1e-6)
        order = np.argsort(-sharpe)  # 0 is most bullish / healthy, 1 is churn / bear
        self.means = self.means[order]
        self.covs = self.covs[order]
        self.pi = self.pi[order]
        self.A = self.A[order][:, order]

    def predict_filtered_proba(self, X):
        """
        Point-in-time causal forward filtering: P(S_t = k | X_{1..t}).
        Strictly zero lookahead: only utilizes past data up to day t.
        """
        X = np.asarray(X)
        if X.ndim == 1:
            X = X[:, np.newaxis]
        N, D = X.shape
        K = self.n_components
        log_B = self._log_emission_prob(X)
        log_pi = np.log(np.maximum(self.pi, 1e-12))
        log_A = np.log(np.maximum(self.A, 1e-12))

        log_alpha = np.zeros((N, K))
        log_alpha[0] = log_pi + log_B[0]
        for t in range(1, N):
            for k in range(K):
                log_alpha[t, k] = log_B[t, k] + logsumexp(log_alpha[t - 1] + log_A[:, k])

        # Normalize across states for each time t
        log_filtered = log_alpha - logsumexp(log_alpha, axis=1, keepdims=True)
        return np.exp(log_filtered)


# Alias
GaussianHMM = GaussianHMM1D2D


def detect_market_regime(df) -> dict:
    """
    從個股歷史日K (建議 >= 60 根) 評估當前市場狀態 (Regime)。
    回傳格式：
    {
        "regime_name": "🟢 順勢波段環境" or "⚠️ 高波震盪市況",
        "regime_code": "healthy" or "adverse",
        "p_healthy": float,
        "p_adverse": float,
        "is_adverse": bool,
        "summary": str,
        "color": str
    }
    """
    if df is None or len(df) < 30:
        return {
            "regime_name": "⚪ 市況資料不足",
            "regime_code": "unknown",
            "p_healthy": 0.50,
            "p_adverse": 0.50,
            "is_adverse": False,
            "summary": "歷史 K 棒數量不足以擬合 HMM 市場狀態 (需 >= 30 根)",
            "color": "#94a3b8"
        }

    try:
        sub = df[["close"]].copy()
        if "ema20" not in df.columns:
            sub["ema20"] = sub["close"].ewm(span=20, adjust=False).mean()
        else:
            sub["ema20"] = df["ema20"]

        sub["ret"] = np.log(sub["close"] / sub["close"].shift(1))
        sub["vol20"] = sub["ret"].rolling(20, min_periods=10).std()
        sub["bias20"] = sub["close"] / sub["ema20"] - 1.0

        valid = sub.dropna().reset_index(drop=True)
        if len(valid) < 25:
            return {
                "regime_name": "⚪ 市況資料不足",
                "regime_code": "unknown",
                "p_healthy": 0.50,
                "p_adverse": 0.50,
                "is_adverse": False,
                "summary": "有效特徵不足",
                "color": "#94a3b8"
            }

        X = valid[["ret", "vol20", "bias20"]].values
        hmm = GaussianHMM(n_components=2, n_iter=20, random_state=42)
        hmm.fit(X)

        probs = hmm.predict_filtered_proba(X)
        p_healthy = float(probs[-1, 0])
        p_adverse = float(probs[-1, 1])

        # 若 adverse 機率 > 50% 或 healthy < 45%
        is_adverse = bool(p_adverse > 0.50 or p_healthy < 0.45)

        if not is_adverse:
            return {
                "regime_name": "🟢 順勢波段環境",
                "regime_code": "healthy",
                "p_healthy": round(p_healthy, 3),
                "p_adverse": round(p_adverse, 3),
                "is_adverse": False,
                "summary": f"HMM 順勢信心度 {round(p_healthy * 100, 1)}%（低波有序推升，適合順勢與拉回佈局）",
                "color": "#22c55e"
            }
        else:
            return {
                "regime_name": "⚠️ 高波震盪市況",
                "regime_code": "adverse",
                "p_healthy": round(p_healthy, 3),
                "p_adverse": round(p_adverse, 3),
                "is_adverse": True,
                "summary": f"HMM 震盪洗盤機率 {round(p_adverse * 100, 1)}%（高波無序易假突破，需提高防守標準）",
                "color": "#eab308"
            }
    except Exception as e:
        return {
            "regime_name": "⚪ 市況計算退避",
            "regime_code": "fallback",
            "p_healthy": 0.50,
            "p_adverse": 0.50,
            "is_adverse": False,
            "summary": f"HMM 計算異常退避: {e}",
            "color": "#94a3b8"
        }

