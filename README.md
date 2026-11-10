# Indian Trading Engine

Research-grade components for an NSE/BSE swing-trading decision engine.

## Champion–challenger shadow runner

`trading_engine.shadow_experiment` compares the production router with one
prospective soft-rule change using the same frozen evidence snapshot.

Safety, liquidity, trigger, structural stop, resistance, minimum net R:R, and
portfolio limits are protected. Challenger output is always `SHADOW_ONLY`,
always has `can_place_order=false`, and never replaces the champion's executable
decision. Raw Larry Williams accumulation/distribution calculations are outside
this module and remain unchanged.

Run the tests:

```bash
python -m unittest discover -s tests -v
```
