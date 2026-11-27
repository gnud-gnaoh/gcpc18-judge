# expected: Accepted
import sys
data = sys.stdin.buffer.read().split()
print(sum(map(int, data[1:])))
