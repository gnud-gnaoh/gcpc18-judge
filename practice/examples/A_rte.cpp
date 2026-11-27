// expected: Run Time Error (out-of-range access throws on the big tests; samples pass)
#include <bits/stdc++.h>
using namespace std;
int main() {
    int n;
    cin >> n;
    vector<long long> a(1000);
    long long s = 0;
    for (int i = 0; i < n; i++) { cin >> a.at(i); s += a.at(i); }
    cout << s << "\n";
}
