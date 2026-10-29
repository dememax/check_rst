.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Versioned performance measurements — check_rst project

#####################
Performance history
#####################

This page is rendered deterministically from host-scoped JSON artifacts.
Times are seconds and peak resident set size (RSS) is MiB.
Measurement timestamps use UTC with one-second precision.
User CPU beside elapsed wall time distinguishes computation from waiting.

*******************
Host environments
*******************

.. list-table:: Recorded host environments
   :header-rows: 1

   * - Environment
     - Label
     - OS
     - Kernel
     - CPU
     - Cores
     - RAM (GiB)
     - Python
     - Docutils
     - Sphinx
   * - E1
     - gl63
     - Gentoo Linux
     - 6.18.57-gentoo
     - Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz
     - 12
     - 46.91
     - 3.14.10
     - 0.23
     - 9.1.0

************
Test suite
************

.. list-table:: Project test-suite measurements
   :header-rows: 1

   * - Measured (UTC)
     - Commit
     - Version
     - Environment
     - Scenario
     - Runs
     - Passed
     - Failed
     - Skipped
     - Errors
     - Xfailed
     - Xpassed
     - Wall median (s)
     - Wall min (s)
     - User median (s)
     - User min (s)
     - System median (s)
     - System min (s)
     - Peak RSS max (MiB)
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - project-test-suite
     - 1
     - 2387
     - 0
     - 0
     - 0
     - 0
     - 0
     - 158.254747
     - 158.254747
     - 140.607069
     - 140.607069
     - 16.188372
     - 16.188372
     - 126.18

************
Benchmarks
************

.. list-table:: Reader and transformation benchmarks
   :header-rows: 1

   * - Measured (UTC)
     - Commit
     - Version
     - Environment
     - Scenario
     - Runs
     - Wall median (s)
     - Wall min (s)
     - User median (s)
     - User min (s)
     - System median (s)
     - System min (s)
     - Peak RSS max (MiB)
     - Structural counts
     - Cold/warm output
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-context-heuristic-toctree
     - 3
     - 0.366184
     - 0.351913
     - 0.340307
     - 0.323087
     - 0.027921
     - 0.021978
     - 40.13
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-context-verified-cold-no-toctree
     - 3
     - 1.297350
     - 1.288721
     - 1.212353
     - 1.184888
     - 0.079760
     - 0.076908
     - 85.39
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-context-verified-cold-toctree
     - 3
     - 1.268707
     - 1.267998
     - 1.188331
     - 1.183613
     - 0.083972
     - 0.078955
     - 85.23
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-context-verified-warm-no-toctree
     - 3
     - 1.025462
     - 1.012031
     - 0.950903
     - 0.947417
     - 0.073992
     - 0.063960
     - 83.45
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-context-verified-warm-toctree
     - 3
     - 1.037932
     - 1.029895
     - 0.958452
     - 0.946435
     - 0.077874
     - 0.067949
     - 83.60
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-outline-heuristic-toctree
     - 3
     - 0.391465
     - 0.361231
     - 0.358601
     - 0.333637
     - 0.031964
     - 0.026970
     - 39.95
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-outline-verified-cold-no-toctree
     - 3
     - 2.188948
     - 2.136842
     - 2.031124
     - 1.966185
     - 0.162930
     - 0.152989
     - 85.04
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-outline-verified-cold-toctree
     - 3
     - 2.163337
     - 2.160621
     - 2.018951
     - 2.011099
     - 0.149771
     - 0.139852
     - 85.10
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-outline-verified-warm-no-toctree
     - 3
     - 1.848034
     - 1.841791
     - 1.694889
     - 1.691326
     - 0.149771
     - 0.146942
     - 83.16
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-large-outline-verified-warm-toctree
     - 3
     - 1.943266
     - 1.894048
     - 1.806066
     - 1.746488
     - 0.141876
     - 0.136844
     - 83.16
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-context-heuristic-toctree
     - 3
     - 0.324079
     - 0.314461
     - 0.294330
     - 0.286161
     - 0.028934
     - 0.028015
     - 40.07
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-context-verified-cold-no-toctree
     - 3
     - 1.231783
     - 1.210628
     - 1.145707
     - 1.127772
     - 0.083994
     - 0.081983
     - 84.56
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-context-verified-cold-toctree
     - 3
     - 1.203655
     - 1.184880
     - 1.118509
     - 1.094509
     - 0.087800
     - 0.082889
     - 84.61
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-context-verified-warm-no-toctree
     - 3
     - 0.927100
     - 0.919368
     - 0.855221
     - 0.845939
     - 0.071825
     - 0.069854
     - 82.94
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-context-verified-warm-toctree
     - 3
     - 0.942213
     - 0.931599
     - 0.878685
     - 0.847339
     - 0.073893
     - 0.061907
     - 82.98
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-outline-heuristic-toctree
     - 3
     - 0.317999
     - 0.316189
     - 0.289052
     - 0.283249
     - 0.028997
     - 0.028005
     - 39.89
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-outline-verified-cold-no-toctree
     - 3
     - 2.043480
     - 2.042614
     - 1.880746
     - 1.880160
     - 0.160808
     - 0.137873
     - 84.30
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-outline-verified-cold-toctree
     - 3
     - 2.077752
     - 2.061214
     - 1.944528
     - 1.925653
     - 0.131706
     - 0.129895
     - 84.16
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-outline-verified-warm-no-toctree
     - 3
     - 1.783236
     - 1.758901
     - 1.651626
     - 1.638458
     - 0.127005
     - 0.118889
     - 82.97
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-large-small-outline-verified-warm-toctree
     - 3
     - 1.795707
     - 1.788046
     - 1.656124
     - 1.644696
     - 0.139685
     - 0.138756
     - 83.01
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-context-heuristic-toctree
     - 3
     - 0.378712
     - 0.368837
     - 0.346348
     - 0.343534
     - 0.026953
     - 0.021958
     - 39.98
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-context-verified-cold-no-toctree
     - 3
     - 1.004153
     - 0.998420
     - 0.922386
     - 0.913125
     - 0.083919
     - 0.073970
     - 82.66
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-context-verified-cold-toctree
     - 3
     - 0.994076
     - 0.991729
     - 0.916604
     - 0.914353
     - 0.074886
     - 0.068900
     - 82.62
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-context-verified-warm-no-toctree
     - 3
     - 0.964382
     - 0.961523
     - 0.894379
     - 0.866484
     - 0.074963
     - 0.068952
     - 82.93
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-context-verified-warm-toctree
     - 3
     - 0.962845
     - 0.949846
     - 0.895125
     - 0.870597
     - 0.071938
     - 0.067009
     - 82.95
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-outline-heuristic-toctree
     - 3
     - 0.348724
     - 0.347400
     - 0.322918
     - 0.320965
     - 0.024993
     - 0.022956
     - 40.11
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-outline-verified-cold-no-toctree
     - 3
     - 1.861345
     - 1.848069
     - 1.731846
     - 1.706103
     - 0.128985
     - 0.121851
     - 82.35
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-outline-verified-cold-toctree
     - 3
     - 1.862209
     - 1.814762
     - 1.709724
     - 1.679042
     - 0.138982
     - 0.135014
     - 82.43
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-outline-verified-warm-no-toctree
     - 3
     - 1.798045
     - 1.787306
     - 1.662547
     - 1.660743
     - 0.135812
     - 0.123886
     - 82.48
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-large-outline-verified-warm-toctree
     - 3
     - 1.813628
     - 1.798603
     - 1.676823
     - 1.663171
     - 0.135902
     - 0.134853
     - 82.77
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-context-heuristic-toctree
     - 3
     - 0.335917
     - 0.334258
     - 0.311972
     - 0.310893
     - 0.022952
     - 0.021998
     - 39.91
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-context-verified-cold-no-toctree
     - 3
     - 0.943237
     - 0.929235
     - 0.862101
     - 0.855485
     - 0.071872
     - 0.067892
     - 81.85
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-context-verified-cold-toctree
     - 3
     - 1.029192
     - 0.978157
     - 0.954910
     - 0.908504
     - 0.068962
     - 0.064966
     - 82.35
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-context-verified-warm-no-toctree
     - 3
     - 0.935766
     - 0.927517
     - 0.859084
     - 0.858574
     - 0.074920
     - 0.066888
     - 81.40
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-context-verified-warm-toctree
     - 3
     - 0.930832
     - 0.886281
     - 0.867272
     - 0.824489
     - 0.061948
     - 0.059890
     - 81.31
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-outline-heuristic-toctree
     - 3
     - 0.315715
     - 0.312812
     - 0.289417
     - 0.287264
     - 0.025947
     - 0.025023
     - 39.69
     - \_parse\_rst=1, \_read\_source=4
     - not compared
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-outline-verified-cold-no-toctree
     - 3
     - 1.878696
     - 1.826518
     - 1.738597
     - 1.673128
     - 0.140851
     - 0.138668
     - 81.61
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-outline-verified-cold-toctree
     - 3
     - 1.884529
     - 1.840613
     - 1.771681
     - 1.710418
     - 0.130880
     - 0.111074
     - 81.63
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-outline-verified-warm-no-toctree
     - 3
     - 1.760906
     - 1.747100
     - 1.644448
     - 1.587512
     - 0.138011
     - 0.116026
     - 81.06
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - generated-small-small-outline-verified-warm-toctree
     - 3
     - 1.806464
     - 1.731257
     - 1.651275
     - 1.592053
     - 0.145914
     - 0.139004
     - 81.25
     - \_build\_sphinx\_env=1, \_parse\_rst=1, \_read\_source=4, \_toctree\_anomalies=1, run\_sphinx=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - public-context-no-toctree-verified-cold
     - 3
     - 3.222987
     - 3.128473
     - 3.059312
     - 2.961333
     - 0.154825
     - 0.152759
     - 116.21
     - \_build\_sphinx\_env=1, \_nested\_inline\_reparse=64, \_parse\_rst=1, \_read\_source=1, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - public-context-no-toctree-verified-warm
     - 3
     - 2.562320
     - 2.464315
     - 2.400289
     - 2.314835
     - 0.144739
     - 0.138940
     - 117.21
     - \_build\_sphinx\_env=1, \_nested\_inline\_reparse=64, \_parse\_rst=1, \_read\_source=1, \_toctree\_anomalies=1
     - yes
   * - 2026-10-29T11:51:18Z
     - 38127a05dd50
     - 0.7.4
     - E1
     - public-context-toctree-heuristic
     - 3
     - 0.764150
     - 0.760186
     - 0.729535
     - 0.716301
     - 0.041900
     - 0.032933
     - 47.68
     - \_nested\_inline\_reparse=64, \_parse\_rst=1, \_read\_source=1
     - not compared
