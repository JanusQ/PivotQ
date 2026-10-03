// Dense complex128 Pauli operations, explicit real arithmetic, no factorization.
#include <complex>
#include <cstdint>
#include <cmath>
#ifdef _OPENMP
#include <omp.h>
#endif
using C=std::complex<double>;
static inline double sign(uint64_t input,uint64_t z,int ny) {
    return (__builtin_parityll(input & z) ^ ((ny>>1)&1)) ? -1.0 : 1.0;
}
extern "C" {
void dense_threads(int n) {
#ifdef _OPENMP
    omp_set_num_threads(n);
#endif
}
void dense_rotate(C* state,uint64_t n,uint64_t x,uint64_t z,int ny,double angle) {
    double* s=reinterpret_cast<double*>(state);double c=std::cos(angle/2),t=std::sin(angle/2);
    if (!x) {
        #pragma omp parallel for schedule(static)
        for(uint64_t i=0;i<n;i++) {
            double r=s[2*i],im=s[2*i+1],v=t*sign(i,z,ny);
            s[2*i]=c*r+v*im;s[2*i+1]=c*im-v*r;
        }
    } else {
        uint64_t bit=x & -x, low=bit-1;
        #pragma omp parallel for schedule(static)
        for(uint64_t k=0;k<n/2;k++) {
            uint64_t i=(k & low)|((k & ~low)<<1),j=i^x;
            double ar=s[2*i],ai=s[2*i+1],br=s[2*j],bi=s[2*j+1],v=t*sign(i,z,ny);
            if(ny&1) {
                s[2*i]=c*ar-v*br;s[2*i+1]=c*ai-v*bi;
                s[2*j]=c*br+v*ar;s[2*j+1]=c*bi+v*ai;
            } else {
                s[2*i]=c*ar+v*bi;s[2*i+1]=c*ai-v*br;
                s[2*j]=c*br+v*ai;s[2*j+1]=c*bi-v*ar;
            }
        }
    }
}
void dense_pauli_add(C* destination,const C* source,uint64_t n,uint64_t x,uint64_t z,int ny,double real,double imag) {
    double* dst=reinterpret_cast<double*>(destination);const double* src=reinterpret_cast<const double*>(source);
    #pragma omp parallel for schedule(static)
    for(uint64_t i=0;i<n;i++) {
        uint64_t j=i^x;double v=sign(j,z,ny),r=src[2*j],im=src[2*j+1];
        if(ny&1){double temp=r;r=-im;im=temp;}
        dst[2*i]+=v*(real*r-imag*im);dst[2*i+1]+=v*(real*im+imag*r);
    }
}
double dense_gradient(const C* lhs,const C* rhs,uint64_t n,uint64_t x,uint64_t z,int ny) {
    const double* l=reinterpret_cast<const double*>(lhs);const double* r=reinterpret_cast<const double*>(rhs);double value=0;
    #pragma omp parallel for reduction(+:value) schedule(static)
    for(uint64_t i=0;i<n;i++) {
        uint64_t j=i^x;double v=sign(j,z,ny);
        value+=v*((ny&1) ? l[2*i]*r[2*j]+l[2*i+1]*r[2*j+1] : l[2*i]*r[2*j+1]-l[2*i+1]*r[2*j]);
    }
    return value;
}
double dense_bilinear(const C* lhs,const C* rhs,uint64_t n,uint64_t x,uint64_t z,int ny) {
    const double* l=reinterpret_cast<const double*>(lhs);const double* r=reinterpret_cast<const double*>(rhs);double value=0;
    #pragma omp parallel for reduction(+:value) schedule(static)
    for(uint64_t i=0;i<n;i++) {
        uint64_t j=i^x;double v=sign(j,z,ny);
        value+=2*v*((ny&1) ? -l[2*i]*r[2*j+1]+l[2*i+1]*r[2*j] : l[2*i]*r[2*j]+l[2*i+1]*r[2*j+1]);
    }
    return value;
}
}
