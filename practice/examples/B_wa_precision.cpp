// expected: Wrong Answer (only 2 decimals; samples pass, 1/3 fails)
#include <bits/stdc++.h>
using namespace std;
int main() {
    int n;
    cin >> n;
    long long s = 0;
    for (int i = 0; i < n; i++) { long long x; cin >> x; s += x; }
    printf("%.2f\n", (double)s / n);
}
