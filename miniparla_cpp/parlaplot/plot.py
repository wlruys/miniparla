import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

plt.rcParams.update({
    'figure.figsize': (7, 5),
    'figure.dpi': 100,
    'text.usetex': True,
    'font.family': 'serif',
    'font.size': 12,
})

def stylize_axes(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    #ax.grid = True
    # ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_tick_params(top='off', direction='in', width=1)
    ax.yaxis.set_tick_params(
        right='off', direction='in', width=1, which='major')


sources = ['thread', 'parla', 'miniparla', 'cpp']

times = [1e3, 5e3, 1e4, 5e4]
colors = ['r', 'g', 'b', 'purple']
rep = {}
for i, t in enumerate(times):
    rep[t] = colors[i]


def plot_speedup(n, d, i, name, df, accesses, frac, times, limit):

    ax = plt.subplot(n, d, i+1)

    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)

    #Compute expected time
    df['expected'] = (df['task_time']*df['n'])/(1e6)

    #Select the data for the given accesses and frac
    df = df[(df['accesses'] == accesses) & (df['frac'] == frac)]

    for task_time in df['task_time'].unique():
        df2 = df[df['task_time'] == task_time]
        if task_time in times:
            ax.plot(df2['workers'], df2['expected']/df2['total_time'], label=str(round(task_time/1e3)) + 'ms', color=rep[task_time])


    ax.set_title(name)
    ax.set_xlabel('Workers')
    ax.set_ylim(0, limit)
    ax.set_xlim(1, 32)
    ax.set_xticks([1, 4, 8, 16, 32])
    ax.xaxis.grid(True, which='major', linestyle='--', linewidth=0.5)
    ax.yaxis.grid(True, which='major', linestyle='--', linewidth=0.2)

    stylize_axes(ax)
    if i == 0:
        ax.set_ylabel('Speedup')

    if i == n-1:
        ax.legend()


file = 'cv.ind.log'
frames = []
times = [1e3, 5e3, 1e4, 5e4]

if 'weak' in file:
    limit = 1
else:
    limit = 20

labels = []

for s in sources:
    name = s + '/' + file
    print(name)
    # Read in the data
    try:
        df = pd.read_csv(name, sep=', ', engine='python')
    except:
        continue
    frames.append(df)
    labels.append(s)

d = len(frames)
n = 1
fig, ax = plt.subplots(n, d)
plt.subplots_adjust(wspace=0.5, hspace=0.5)

for i, name in enumerate(labels):
    plot_speedup(n, d, i, name, frames[i], 1, 0, times, limit)

plt.savefig(file+'.png', bbox_inches='tight')
plt.show()