"""Plot measured training/50 fs results directly with Matplotlib; no figure skill."""
import argparse,json,csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    md=a.run/'aimd_50fs';status=json.loads((md/'status.json').read_text())
    if status['status']!='completed':raise ValueError('Completed real trajectory required; no synthetic or incomplete 50 fs plots')
    history=json.loads((a.run/'history.json').read_text());spec=json.loads((a.run/'spec.json').read_text())
    frames=[np.load(p) for p in sorted(md.glob('frame_*.npz'))]
    if len(frames)!=501 or float(frames[-1]['time_fs'])!=50.:raise ValueError('Expected 501 frames including t=0')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
    def save(fig,name):
        fig.savefig(a.output/f'{name}.svg',bbox_inches='tight');fig.savefig(a.output/f'{name}.png',dpi=200,bbox_inches='tight');plt.close(fig)
    epochs=[r['epoch'] for r in history];fig,axes=plt.subplots(1,3,figsize=(12,3.3),layout='constrained')
    for ax,label,train,val in [(axes[0],'Energy RMSE (eV)','online_train_energy_rmse_ev','validation_energy_rmse_ev'),(axes[1],'Force RMSE (eV/angstrom)','online_train_force_rmse_ev_per_A','validation_force_rmse_ev_per_A')]:
        ax.plot(epochs,[r[train] for r in history],label='Training (online)',color='#2563a6')
        ax.plot(epochs,[r[val] for r in history],label='Validation',color='#d77a25');ax.set(xlabel='Epoch',ylabel=label);ax.legend()
    axes[2].plot(epochs,[r['validation_loss'] for r in history],color='#d77a25');axes[2].set(xlabel='Epoch',ylabel='Normalized validation E + F loss')
    fig.suptitle('Ten-water dense-state energy–force training');save(fig,'training_energy_force')
    rows=[]
    for f in frames:
        error=f['forces']-f['reference_forces'];oh=f['oh_lengths_A'];angle=f['hoh_angles_deg']
        rows.append(dict(time_fs=float(f['time_fs']),potential_ev=float(f['potential_ev']),kinetic_ev=float(f['kinetic_ev']),total_ev=float(f['total_ev']),temperature_K=float(f['temperature_K']),energy_error_ev=float(f['potential_ev']-f['reference_energy_ev']),force_rmse_ev_per_A=float(np.sqrt(np.mean(error**2))),oh_mean_A=float(oh.mean()),oh_min_A=float(oh.min()),oh_max_A=float(oh.max()),hoh_mean_deg=float(angle.mean()),hoh_min_deg=float(angle.min()),hoh_max_deg=float(angle.max()),min_oo_A=float(f['min_oo_A']),net_force_norm=float(np.linalg.norm(f['net_force'])),torque_norm=float(np.linalg.norm(f['torque']))))
    with (a.output/'aimd_source_data.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    array=lambda name:np.array([r[name] for r in rows]);t=array('time_fs')
    fig,axes=plt.subplots(3,2,figsize=(10,9),layout='constrained');axes=axes.ravel()
    axes[0].plot(t,1000*(array('total_ev')-rows[0]['total_ev']));axes[0].set_ylabel('Total energy drift (meV)')
    axes[1].plot(t,array('temperature_K'));axes[1].set_ylabel('Temperature (K)')
    axes[2].plot(t,1000*array('energy_error_ev'));axes[2].set_ylabel('Energy error vs MB-pol (meV)')
    axes[3].plot(t,array('force_rmse_ev_per_A'));axes[3].set_ylabel('Force RMSE vs MB-pol (eV/angstrom)')
    for ax,prefix,unit,count in [(axes[4],'oh','A',20),(axes[5],'hoh','deg',10)]:
        ax.fill_between(t,array(f'{prefix}_min_{unit}'),array(f'{prefix}_max_{unit}'),alpha=.2,label=f'Range across {count} values')
        ax.plot(t,array(f'{prefix}_mean_{unit}'),label='Mean');ax.set_ylabel('OH length (angstrom)' if prefix=='oh' else 'HOH angle (degrees)');ax.legend(fontsize=8)
    for i,ax in enumerate(axes):ax.set_xlabel('Time (fs)');ax.set_title(chr(97+i),loc='left',fontweight='bold');ax.grid(alpha=.15)
    fig.suptitle('50 fs NVE trajectory — one ten-water validation cluster');save(fig,'aimd_50fs_evaluation')
    fig,axes=plt.subplots(1,3,figsize=(12,3.3),layout='constrained')
    for ax,name,label in zip(axes,['net_force_norm','torque_norm','min_oo_A'],['Net force norm (eV/angstrom)','Torque norm (eV)','Minimum OO distance (angstrom)']):
        ax.plot(t,array(name));ax.set(xlabel='Time (fs)',ylabel=label);ax.ticklabel_format(axis='y',style='sci',scilimits=(-3,3))
    save(fig,'aimd_force_balance')
    for name in ['metadata.json','metrics.json']:(a.output/name).write_text((md/name).read_text())
    (a.output/'README.md').write_text('Plots use actual completed training and 501 trajectory frames. MB-pol errors compare identical geometries. Shaded geometry bands are ranges across bonds/angles, not confidence intervals. This is one 50 fs trajectory and does not establish long-time dynamics accuracy. Online training metrics use changing within-epoch weights. No synthetic data or smoothing.\n')

if __name__=='__main__':main()
