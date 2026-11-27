// expected: Time Limit Exceeded (quadratic; samples pass)
#include <bits/stdc++.h>
using namespace std;
int main() {
    int n;
    cin >> n;
    vector<long long> a(n);
    for (auto &x : a) cin >> x;
    long long s = 0;
    for (int i = 0; i < n; i++)
        for (int j = 0; j <= i; j++)
            if (j == i) s += a[j];
    cout << s << "\n";
}
