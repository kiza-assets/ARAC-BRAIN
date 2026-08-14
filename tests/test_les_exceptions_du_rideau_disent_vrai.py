"""LES EXCEPTIONS DU RIDEAU DE LECTURE DISENT VRAI — VÉRIFIÉ, PAS CRU.

CE QUE CE GARDE MESURE, EN UNE PHRASE
=====================================
Le rideau de lecture n'énumère pas ce qui est interdit — il énumère ce qui est
PERMIS, et chaque permission porte une raison écrite. Ce fichier vérifie les
raisons : une exception dont la justification a cessé d'être vraie est une porte
que personne ne rouvrira jamais, parce qu'elle a déjà l'air examinée.

DEUX RAISONS FAUSSES ONT ÉTÉ TROUVÉES, ET ELLES SE RESSEMBLENT
==============================================================
1. `/proc`, justifié par « `/proc` et `/sys` ne portent le cerveau de
   personne ». `/proc/<pid>/environ` d'un service arac est la copie VERBATIM de
   son coffre (l'unité porte `EnvironmentFile=`) : jeton porteur et DSN avec mot
   de passe. La raison était fausse ; le trou a vécu deux manches. Il est fermé
   et éprouvé dans `test_le_rideau_ne_lit_pas_le_proc_du_voisin.py`.

2. `/dev`, justifié par « `/dev/null` s'écrit, `/dev/urandom` se lit ». Les deux
   moitiés sont vraies. Ce qu'elles justifiaient ne l'était pas : la racine
   entière était accordée, en lecture au rideau et en ÉCRITURE COMPLÈTE au
   noyau. Sous `root` — et cette suite tourne sous `root` — cela ouvrait
   `/dev/sda` et `/dev/mem` : les disques bruts de la machine et sa mémoire
   vive, c'est-à-dire tous les coffres à la fois, et de quoi les écraser.

   MESURÉ, AVANT ET APRÈS, sur cette machine où `/dev/sda` existe :
   · avant — barrière posée avec « /dev » en écriture complète :
     `libc.open("/dev/sda", O_RDWR)` → OUVERT ; `/dev/mem` → OUVERT ;
   · après  — `libc.open("/dev/sda")` → EACCES, `/dev/mem` → EACCES,
     `/dev/shm` → EACCES, pendant que `/dev/null` et `/dev/zero` s'ouvrent et
     que `pty.openpty()` fonctionne.
   Et la liste des portes de `/dev` n'est pas un pari : espion posé sur toutes
   les portes de lecture pendant une session complète (5 052 tests), la suite
   ouvre UN seul chemin sous `/dev`, et c'est `/dev/null`.

LA FORME DE CE GARDE, ET POURQUOI ELLE VAUT MIEUX QU'UNE RELECTURE
==================================================================
Une raison écrite se relit une fois puis se croit. On en fait donc une question
mécanique : pour chaque endroit où le PRODUIT dépose un secret, le rideau
doit-il dire non ? La liste ci-dessous vient de ce que le bootstrap installe —
pas de ce qui existe sur cette machine : aucun nom de cerveau réel n'est
demandé, aucun répertoire de l'hôte n'est énuméré. Le jour où une racine
nouvelle recouvrira l'un de ces endroits, ce test rougira, quelle que soit la
phrase écrite au-dessus d'elle.
"""

from __future__ import annotations

import ctypes
import os

import pytest

from tests import garde_hermetique as g
from tests.garde_hermetique import RefusHermetique

#: UN CERVEAU IMAGINAIRE. On ne demande jamais le nom d'un cerveau réel : ce
#: serait énumérer l'hôte, c'est-à-dire commettre l'indiscrétion qu'on garde.
VOISIN = "cerveau_imaginaire_du_garde"

#: LÀ OÙ LE PRODUIT DÉPOSE CE QUI COMPTE. Chacun vient de ce que le bootstrap
#: écrit : le coffre (`EnvironmentFile`), les sauvegardes, l'état, les journaux
#: d'accès. Aucun ne doit être lisible par la suite, par quelque exception que
#: ce soit.
QUI_PORTENT_UN_CERVEAU = (
    f"/etc/arac/{VOISIN}/arac.env",
    f"/etc/arac/{VOISIN}",
    "/etc/arac",
    f"/var/backups/arac/{VOISIN}/adieu.dump",
    f"/var/lib/arac/{VOISIN}/etat.json",
    f"/var/log/arac/{VOISIN}/acces.log",
    f"/opt/{VOISIN}/.env",
    "/root/.pgpass",
    # LA PORTE DU DÉPÔT DE SAUVEGARDES D'UN VOISIN et les unités qui font
    # vivre son cerveau. Elles étaient recouvertes — sans une ligne écrite —
    # par `sys.base_prefix`, qui vaut `/usr` : le rideau de lecture accordait
    # donc `/usr/local`, que le rideau des données déclare pourtant porteur de
    # cerveau. Mesuré, rideau seul : `os.mkdir` RÉUSSISSAIT sous
    # `/usr/local/bin/`, sous `/usr/bin/` et sous `/usr/lib/systemd/system/`.
    "/usr/local/bin/arac-depot-sauvegardes",
    f"/etc/systemd/system/arac-{VOISIN}-api.service",
    # LE TROISIÈME ENDROIT MESURÉ, RESTÉ OUVERT UNE MANCHE DE PLUS. La raison
    # écrite juste au-dessus en nommait TROIS ; la correction en avait fermé
    # deux. Ce n'est pas un oubli d'écriture, c'est le critère qui était trop
    # étroit : `_RETRANCHEES` listait « où le produit ÉCRIT », alors que le
    # danger est « où le SYSTÈME LIT ». Le produit pose ses unités dans
    # `/etc/systemd/system` ; systemd les cherche dans douze répertoires
    # (`systemd-analyze unit-paths`), dont `/usr/lib/systemd/system`, que
    # `sys.base_prefix` recouvre. Une SURCHARGE écrite là s'applique à l'unité
    # du voisin au prochain `daemon-reload`, sans que son fichier ait bougé.
    f"/usr/lib/systemd/system/arac-{VOISIN}-api.service",
    f"/usr/lib/systemd/system/arac-{VOISIN}-api.service.d/99-detour.conf",
    # Les deux familles voisines, entrées par la même porte : `systemd-tmpfiles`
    # lit `/usr/lib/tmpfiles.d` (une ligne `R!` y efface un répertoire entier au
    # démarrage — les sauvegardes d'un voisin), `systemd-sysusers` lit
    # `/usr/lib/sysusers.d` (les comptes `arac_<base>` sous lesquels tournent
    # les services d'un cerveau).
    f"/usr/lib/tmpfiles.d/arac-{VOISIN}.conf",
    f"/usr/lib/sysusers.d/arac-{VOISIN}.conf",
    # Le disque brut et la mémoire vive : tous les coffres à la fois.
    "/dev/sda", "/dev/mem", "/dev/kmem", "/dev/shm",
    # Le coffre d'un service, recopié par le noyau dans son environnement.
    "/proc/1/environ", "/proc/1/cmdline",
)

#: LES SECRETS DE L'HÔTE — pas un cerveau, et à refuser quand même.
#:
#: Ce dépôt garde les cerveaux ; il n'a pas pour autant le droit de lire la clé
#: privée du serveur qui l'héberge. Cette liste-ci a été ajoutée parce que la
#: raison écrite au-dessus de `/etc/ssl` disait, mot pour mot : « Ce sont des
#: certificats PUBLICS ; la clé privée d'un serveur ne vit pas là » — alors que
#: sur Debian et Ubuntu, elle vit très exactement là, dans `/etc/ssl/private/`.
#: Mesuré, rideau seul : `open("/etc/ssl/private/ssl-cert-snakeoil.key")`
#: rendait `-----BEGIN PRIVATE KEY-----`. La racine a été resserrée sur
#: `/etc/ssl/certs`, et cette liste empêche `/etc/ssl` de revenir en entier.
SECRETS_DE_L_HOTE = (
    "/etc/ssl/private", "/etc/ssl/private/ssl-cert-snakeoil.key",
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers",
    "/root/.ssh/id_ed25519", "/etc/ssh/ssh_host_ed25519_key",
)


@pytest.mark.parametrize("chemin", SECRETS_DE_L_HOTE)
def test_aucune_exception_ne_recouvre_un_secret_de_la_machine(chemin):
    """Ce qui appartient à la MACHINE, et non à un cerveau, se refuse aussi."""
    assert g._lecture_toleree(chemin) is False, (
        f"Une exception du rideau recouvre « {chemin} » — un secret de l'hôte, "
        "pas un cerveau, et refusé pour la même raison : une suite de tests "
        "n'a rien à y lire. Relisez la raison écrite au-dessus de la racine "
        f"fautive.\nRacines accordées : {g._racines_de_lecture()}")


def test_aucune_racine_calculee_ne_recouvre_ce_que_le_produit_installe():
    """LA RACINE QU'ON N'ÉCRIT PAS EST CELLE QU'ON NE RELIT JAMAIS.

    `sys.prefix`, `sys.base_prefix` et `sysconfig.get_paths()` entrent dans la
    liste des racines sans qu'aucune ligne ne les nomme. Sur une machine
    ordinaire, `sys.base_prefix` vaut `/usr` — et accorde donc le parent des
    trois racines que la liste nomme soigneusement une par une. On vérifie donc
    la propriété plutôt que la liste : quelle que soit la racine, aucun endroit
    où le produit dépose quelque chose ne doit être recouvert.
    """
    racines = g._racines_de_lecture()
    for endroit in g._RETRANCHEES:
        assert g._lecture_toleree(endroit) is False, (
            f"« {endroit} » est recouvert par une racine. Racines : {racines}")
        assert g._lecture_toleree(endroit + "/quoi-que-ce-soit") is False


def test_le_retranchement_ne_ferme_pas_l_installation_de_python():
    """Le grain reste fin : ce que la machinerie demande vraiment passe.

    Un retranchement trop large se paie en session avortée, et c'est ainsi
    qu'on débranche un garde. `/usr/lib` et l'installation Python restent
    ouverts ; seul ce que le produit installe est retranché.
    """
    import sysconfig
    assert g._lecture_toleree(sysconfig.get_paths()["stdlib"]) is True
    assert g._lecture_toleree("/usr/lib") is True
    # Un binaire de la distribution, nommé sans le citer : ce fichier ne doit
    # pas écrire le chemin d'un exécutable de l'hôte (le garde de la porte du
    # sous-processus le balaie, et il a raison).
    assert g._lecture_toleree(os.path.join("/usr", "lib", "os-release")) is True


def test_la_racine_des_certificats_ne_redevient_pas_etc_ssl_en_entier():
    """La liste elle-même, et pas seulement les chemins qu'on a pensé à écrire.

    Une machine dont la clé de serveur porte un autre nom laisserait passer
    l'épreuve ci-dessus sans que rien ne soit fermé. On regarde donc la racine.
    """
    racines = g._racines_de_lecture()
    assert "/etc/ssl" not in racines, (
        "`/etc/ssl` est redevenu une racine entière : cela rouvre "
        "`/etc/ssl/private`, où vit la clé privée du serveur. Ce que la "
        "machinerie demande est `/etc/ssl/certs` — mesurable par "
        "`ssl.get_default_verify_paths()`.")
    assert g._lecture_toleree("/etc/ssl/certs/ca-certificates.crt") is True, (
        "Le grain est devenu trop serré : les autorités de certification "
        "publiques sont lues à l'import de `ssl`.")


@pytest.mark.parametrize("chemin", QUI_PORTENT_UN_CERVEAU)
def test_aucune_exception_ne_recouvre_un_endroit_qui_porte_un_cerveau(chemin):
    """La question posée à CHAQUE exception, d'un coup et sans les relire."""
    assert g._lecture_toleree(chemin) is False, (
        f"Une exception du rideau recouvre « {chemin} », c'est-à-dire un "
        "endroit où le produit dépose un secret. Relisez la raison écrite "
        "au-dessus de la racine fautive dans `_racines_de_lecture` : c'est "
        "elle qui a cessé d'être vraie.\nRacines accordées : "
        f"{g._racines_de_lecture()}")


@pytest.mark.parametrize("chemin", QUI_PORTENT_UN_CERVEAU + SECRETS_DE_L_HOTE)
def test_aucun_detour_par_un_lien_magique_ne_recouvre_ces_endroits(chemin):
    """LA MÊME QUESTION, POSÉE PAR L'AUTRE ÉCRITURE DU MÊME ENDROIT.

    Toute la table ci-dessus se lisait, jusqu'à cette manche, en préfixant
    `/proc/self/root` : le chemin restait sous la racine accordée `/proc` pour
    un jugement de texte, et le noyau le réécrivait vers le coffre. Une table
    d'exceptions ne vaut donc pas seulement pour les chemins qu'on y écrit, mais
    pour tous ceux qui atteignent le même endroit.
    """
    if not os.path.islink("/proc/self/root"):
        pytest.skip("pas de lien magique /proc/self/root sur cette machine")
    if chemin.startswith("/proc/"):
        pytest.skip("déjà un chemin de /proc : le détour n'ajoute rien")
    assert g._lecture_toleree("/proc/self/root" + chemin) is False
    assert g._donnee_toleree("/proc/self/root" + chemin) is False


@pytest.mark.parametrize("chemin", ["/dev/null", "/dev/zero", "/dev/urandom",
                                    "/dev/random", "/dev/full", "/dev/tty",
                                    "/dev/ptmx", "/dev/pts/3", "/dev/fd/1"])
def test_les_portes_de_dev_dont_la_suite_a_besoin_restent_ouvertes(chemin):
    """Un grain trop serré se fait débrancher : c'est ainsi qu'on perd un garde.

    `/dev/null` est ouvert 389 fois dans ce dépôt, `/dev/zero` sert à fabriquer
    un fichier long dans `test_le_juge_ne_tire_pas_au_sort`, et `pty.openpty()`
    passe par `/dev/ptmx` et `/dev/pts`.
    """
    assert g._lecture_toleree(chemin) is True


def test_dev_null_s_ecrit_vraiment_et_le_disque_brut_non():
    """La preuve par l'usage, pas par la table."""
    with open("/dev/null", "w") as fh:
        fh.write("ceci ne va nulle part")
    with pytest.raises(RefusHermetique):
        open("/dev/sda", "rb")


def test_le_noyau_refuse_le_disque_brut_quand_la_barriere_est_posee():
    """CE QUE LE RIDEAU NE PEUT PAS TENIR SEUL, LE NOYAU LE TIENT.

    On appelle `libc.open` directement — c'est-à-dire la maille que le rideau
    de Python ne ferme pas, et qu'il déclare lui-même ne pas fermer. Si la
    seconde barrière est posée, le refus doit venir du noyau (EACCES).
    """
    from tests.conftest import VERDICT_DE_LA_SECONDE_BARRIERE

    if not VERDICT_DE_LA_SECONDE_BARRIERE.startswith("POSÉE"):
        pytest.skip(f"barrière absente : {VERDICT_DE_LA_SECONDE_BARRIERE[:60]}")
    if not os.path.exists("/dev/sda"):
        pytest.skip("pas de disque brut nommé /dev/sda sur cette machine")

    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    fd = libc.open(b"/dev/sda", os.O_RDONLY)
    if fd >= 0:  # pragma: no cover — la barrière ne tient plus
        libc.close(fd)
        pytest.fail("Le noyau laisse ouvrir le disque brut de la machine "
                    "malgré la seconde barrière : la règle `/dev` accorde plus "
                    "que les fichiers nommés dans `_PORTES_DE_DEV`.")
    assert ctypes.get_errno() == 13


def test_la_raison_de_dev_ne_redevient_pas_une_racine():
    """Le retour de `/dev` comme RACINE se refuse mécaniquement.

    Ce n'est pas la même chose que de vérifier les chemins : une racine peut
    revenir dans la liste sans qu'aucun des chemins éprouvés ici ne change de
    verdict, si le disque de la machine s'appelle autrement (`/dev/vda`,
    `/dev/nvme0n1`). On regarde donc la liste elle-même.
    """
    racines = g._racines_de_lecture()
    assert "/dev" not in racines, (
        "`/dev` est redevenu une racine. Sous root, cela rouvre les "
        "périphériques bloc et `/dev/mem`. Les fichiers dont la suite a besoin "
        "sont nommés un par un dans `_PORTES_DE_DEV`.")
    assert g._PORTES_DE_DEV, "la liste des portes de /dev a disparu"
