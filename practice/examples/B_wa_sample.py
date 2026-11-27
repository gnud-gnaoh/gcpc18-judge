# expected: Wrong Answer on sample 1 (integer division), shows the diff
n = int(input())
v = list(map(int, input().split()))
print(sum(v) // n)
