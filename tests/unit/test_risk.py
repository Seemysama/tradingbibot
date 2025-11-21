from core.risk import RiskGuard, RiskConfig, EquityState

def test_risk_lockout_on_seq_losses():
    rg = RiskGuard(RiskConfig(max_seq_losses=2), EquityState(10000,10000,10000,10000,0))
    assert rg.can_trade()
    rg.record_trade_result(-100)
    assert rg.can_trade()
    rg.record_trade_result(-50)
    assert not rg.can_trade()


def test_risk_panic():
    rg = RiskGuard(RiskConfig(), EquityState(10000,10000,10000,10000,0))
    rg.panic()
    assert not rg.can_trade()
