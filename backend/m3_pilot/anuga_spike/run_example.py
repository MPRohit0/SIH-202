"""ANUGA quickstart example (runup.py) -- water driven up a linear slope.

Source: https://anuga.readthedocs.io/en/latest/examples/script_simple_example.html
Run as a spike to confirm the ANUGA install works end-to-end.
"""
import time
import anuga
from math import sin, pi, exp

t_start = time.time()

domain = anuga.rectangular_cross_domain(10, 10)
domain.set_name('runup_spike')

def topography(x, y):
    return -x / 2

domain.set_quantity('elevation', topography)
domain.set_quantity('friction', 0.1)
domain.set_quantity('stage', -0.4)

Br = anuga.Reflective_boundary(domain)
Bw = anuga.Time_boundary(domain=domain,
    function=lambda t: [(0.1 * sin(t * 2 * pi) - 0.3) * exp(-t), 0.0, 0.0])

domain.set_boundary({'left': Br, 'right': Bw, 'top': Br, 'bottom': Br})

for t in domain.evolve(yieldstep=0.5, finaltime=10.0):
    domain.print_timestepping_statistics()

print(f"WALLCLOCK_SECONDS={time.time() - t_start:.2f}")
