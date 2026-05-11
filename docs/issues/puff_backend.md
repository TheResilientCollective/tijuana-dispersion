# Implement Lagrangian puff backend

## Why

The current Gaussian plume backend assumes steady-state. This breaks down for transient releases — exactly the spill events that drive the highest observed concentrations. CALPUFF-style Gaussian puff modeling captures non-stationarity correctly while staying lightweight enough to run in-process on Railway.

The `LagrangianPuffBackend` class in `backends.py` is currently a stub that raises `NotImplementedError`. This issue is to fill it in.

## Scope

A pure-Python (numpy) implementation of a Gaussian puff model. The class signature is already defined; the body needs to:

1. At each timestep, release one Gaussian puff per source with mass = `emission_rate_g_s × Δt`.
2. Advect existing puffs by the current wind vector.
3. Grow each puff's σ_y, σ_z as functions of age (use Briggs σ formulas with x = u × age).
4. Compute concentration at each receptor as the sum over all active puffs of the standard Gaussian puff formula.
5. Deactivate puffs that leave the domain or fall below a concentration threshold.

Estimated implementation: ~300 lines.

## Acceptance criteria

- [ ] `LagrangianPuffBackend.run_forward(...)` returns a concentration array with the correct shape.
- [ ] For a steady-wind, single-source case, results agree with `LocalGaussianPlumeBackend` to within 10% at receptors > 200 m downwind. (The puff model approaches the plume model in steady-state.)
- [ ] For a step-change emission case (zero → 1 g/s at t=12h), the puff model shows the expected delayed-then-rising signal at downwind receptors; the plume model would step instantly. Test this in `tests/test_puff_backend.py`.
- [ ] Performance: 72-hour, 38-source, 3-receptor run completes in < 5 seconds on Railway hobby tier.
- [ ] Memory: peak resident memory < 500 MB for the same workload.
- [ ] Type-checks under `mypy --strict`. Coverage ≥ 80% on the new module.

## Out of scope

- Wet/dry deposition (atmospheric loss is negligible at our 1-hour transport timescale).
- Buoyant plume rise (sources are at ground level).
- Chemistry (H₂S oxidation is slow enough to ignore).

## References

- Briggs (1973), "Diffusion estimation for small emissions"
- CALPUFF technical guidance, Chapter 2.

## Estimated effort

One weekend. Well-scoped, no ambiguous design decisions.
