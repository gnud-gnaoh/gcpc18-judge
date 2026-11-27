#!/usr/bin/env python3
"""Writes the test data of the practice contest into practice/problems/. Deterministic."""
import os
import random
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))


def write(letter, group, name, nums, answer):
    d = os.path.join(HERE, "problems", letter, "data", group)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".in"), "w") as f:
        f.write(f"{len(nums)}\n{' '.join(map(str, nums))}\n")
    with open(os.path.join(d, name + ".ans"), "w") as f:
        f.write(f"{answer}\n")


def avg(nums):
    q = Fraction(sum(nums), len(nums))
    return f"{q.numerator // q.denominator}.{(q - q.numerator // q.denominator) * 10**10 // 1:010d}"


def main():
    rnd = random.Random(2018)
    a = [
        ("sample", "1", [1, 2, 3]),
        ("sample", "2", [-5, 10]),
        ("secret", "01-single", [7]),
        ("secret", "02-small", [rnd.randint(-100, 100) for _ in range(50)]),
        ("secret", "03-big-positive", [rnd.randint(9 * 10**8, 10**9) for _ in range(10**6)]),
        ("secret", "04-big-negative", [-10**9] * 10**6),
    ]
    for g, n, nums in a:
        write("A", g, n, nums, sum(nums))
    b = [
        ("sample", "1", [1, 2]),
        ("sample", "2", [10, 10, 10]),
        ("secret", "01-single", [0]),
        ("secret", "02-thirds", [1, 0, 0]),
        ("secret", "03-random", [rnd.randint(0, 10**6) for _ in range(10**5)]),
    ]
    for g, n, nums in b:
        write("B", g, n, nums, avg(nums))


if __name__ == "__main__":
    main()
