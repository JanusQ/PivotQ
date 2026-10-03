#include "bblock/system.h"
#include <memory>
#include <map>
#include <string>
#include <cmath>
static std::map<int,std::unique_ptr<bblock::System>> systems;
static std::string config;
static std::string error;
extern "C" {
void configure(const char* c) { config=c; systems.clear(); }
const char* last_error() {return error.c_str();}
int evaluate(int n, const double* xyz, double* out, double* grad, int full) {
 try {
  if(!systems.count(n)) {
   auto s=std::unique_ptr<bblock::System>(new bblock::System());
   for(int i=0;i<n;i++) s->AddMonomer(std::vector<double>(xyz+9*i,xyz+9*i+9),{"O","H","H"},"h2o");
   s->Initialize(); s->SetUpFromJson(config); systems[n]=std::move(s);
  }
  auto &s=*systems[n]; s.SetRealXyz(std::vector<double>(xyz,xyz+9*n));
  if(full) {out[0]=s.Energy(true); auto g=s.GetRealGrads(); for(int i=0;i<9*n;i++) grad[i]=g[i];}
  else {s.Electrostatics(false);out[0]=s.GetPermanentElectrostaticEnergy();out[2]=s.GetInducedElectrostaticEnergy();out[1]=s.Dispersion(false);}
  for(int i=0;i<(full?1:3);i++) if(!std::isfinite(out[i])) throw std::runtime_error("Nonfinite MBX energy");
  return 0;
 } catch(const std::exception &e) {error=e.what();systems.clear();return 1;} catch(...) {error="MBX exception";systems.clear();return 2;}
}
}
