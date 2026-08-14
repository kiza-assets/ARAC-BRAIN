-- ============================================================================
-- QUI A LE DROIT D'ÉCRIRE, ET AVEC QUELS RÉGLAGES
-- ============================================================================
--
-- Deux tables sont peuplées ici, et elles répondent à deux questions
-- différentes :
--
--   arac.nodes        « De quels postes le cerveau accepte-t-il quelque chose ? »
--   arac.arac_config  « Avec quelles constantes raisonne-t-il ? »
--
-- ----------------------------------------------------------------------------
-- POURQUOI arac.nodes EXISTE — le garde-fou qu'on ne voit pas
-- ----------------------------------------------------------------------------
--
-- Toute conversation, tout atome, toute session porte un `node_id`, et une clé
-- étrangère exige qu'il soit déclaré ICI. Un poste inconnu ne peut rien
-- déposer : sa requête échoue avant d'avoir touché la mémoire.
--
-- C'est ce qui empêche votre cerveau d'avaler n'importe quoi — et c'est aussi
-- ce qui rend chaque savoir attribuable à sa source des mois plus tard.
--
-- ----------------------------------------------------------------------------
-- VOTRE POSTE — ce fichier a besoin de le connaître
-- ----------------------------------------------------------------------------
--
-- Le `node_id` n'est pas écrit ici : il est le vôtre, décidé pendant
-- l'entretien d'installation et consigné dans `config/brain.toml`. Passez-le
-- en variable psql.
--
-- LA COMMANDE D'AVANT VISAIT LE CERVEAU DE QUELQU'UN D'AUTRE. Elle disait
-- `psql -d arac`, sans `-p`. Ce fichier prenait donc soin de ne pas deviner
-- votre `node_id` — « un node_id inventé ouvrirait exactement la porte que
-- cette table sert à tenir fermée », dit le paragraphe suivant, et il a
-- raison — tout en devinant votre BASE et votre GRAPPE, ce qui est la même
-- faute, en pire : le seed serait allé s'écrire dans le cerveau du voisin.
--
-- `arac` est le nom qu'avait la base de l'auteur. La vôtre en a un autre, et
-- `psql` sans `-p` parle à la grappe 5432, pas nécessairement à la vôtre. Les
-- deux valeurs vivent dans le coffre de VOTRE cerveau :
--
--     ARAC_ENV=/etc/arac/<votre-base>/arac.env
--     psql -p "$(sudo sed -n 's/^ARAC_DB_PORT=//p' "$ARAC_ENV")" \
--          -d "$(sudo sed -n 's/^ARAC_DB=//p'      "$ARAC_ENV")" \
--          -v ON_ERROR_STOP=1 \
--          -v arac_node_id="$(python3 -c \
--             'import arac_runtime; print(arac_runtime.node_id())')" \
--          -f db/seeds/01_nodes_and_config.sql
--
-- Sans cette variable, le script s'arrête avec un message qui vous renvoie à
-- l'entretien. Il ne devine pas : un `node_id` inventé ouvrirait exactement la
-- porte que cette table sert à tenir fermée.
--
-- ----------------------------------------------------------------------------
-- IDEMPOTENT
-- ----------------------------------------------------------------------------
--
-- `ON CONFLICT DO NOTHING` partout : rejouer ce fichier ne crée aucun doublon
-- et n'écrase AUCUNE valeur que vous auriez ajustée en cours de route. Un seed
-- qui réécrit ses valeurs efface les réglages de l'exploitant — c'est une
-- trahison silencieuse, et elle n'arrive pas ici.
-- ============================================================================

\set ON_ERROR_STOP on

-- Le node_id est-il fourni ? Sinon on pose une valeur vide, et le bloc suivant
-- refuse d'aller plus loin en expliquant pourquoi.
\if :{?arac_node_id}
\else
\set arac_node_id ''
\endif

DO $$
BEGIN
    IF :'arac_node_id' = '' THEN
        RAISE EXCEPTION USING MESSAGE =
            'Aucun node_id fourni. Ce cerveau ne saurait pas de quel poste '
            'acceptent ses conversations, donc il les refuserait toutes. '
            'Relancez avec -v arac_node_id=<votre-node-id>, ou passez '
            'l''entretien : python3 bootstrap/wizard.py';
    END IF;
END $$;

BEGIN;

-- ----------------------------------------------------------------------------
-- LES POSTES
--
-- Trois familles, distinguées par ce qu'elles coûtent et par ce qu'elles font :
--
--   account = 'human'   ce que vous tapez vous-même, sur votre abonnement ;
--   account = 'agent'   ce qu'un agent produit en consommant une clé d'API
--                       facturée à l'usage — c'est LÀ que part l'argent ;
--   account = 'system'  un cron, une purge : ça ne coûte rien.
--
--   role = 'owner_producer'  a le droit d'écrire du savoir de premier rang ;
--   role = 'agent'           écrit sous audit ;
--   role = 'service'         ne fait que transporter ou entretenir.
--
-- Les seuils de silence (`silent_warn` / `silent_critical`, en minutes) sont
-- calibrés PAR POSTE, jamais globalement. Un défaut unique produit soit un
-- chien de garde qui hurle sur un portable en veille, soit un chien de garde
-- qui dort pendant qu'un cron est mort depuis trois jours. Les deux se
-- terminent de la même façon : plus personne ne regarde les alertes.
--
-- Tout est `active = FALSE` sauf votre poste. Activez un service le jour où
-- vous l'installez, pas avant : un service déclaré actif et absent est une
-- alarme permanente.
-- ----------------------------------------------------------------------------
INSERT INTO arac.nodes (
    node_id, account, owner, role, auditor_kind,
    expected_cadence_minutes, silent_warn_minutes, silent_critical_minutes,
    quiet_hours_local, active
) VALUES
    -- VOUS. Aucune cadence attendue : un humain n'a pas de fréquence.
    -- Seuils larges (12 h / 48 h) : un week-end sans écrire est normal.
    (:'arac_node_id',            'human',  'owner',  'owner_producer', NULL, NULL, 720, 2880, NULL, TRUE),

    -- Les agents de digestion. Le cerveau digère par CYCLES, pas en continu :
    -- l'état de repos entre deux cycles est normal, et les seuils le disent.
    ('arac-curator',             'agent',  'system', 'agent',   'curator',   1440, 1500, 1800, NULL, FALSE),
    ('arac-cortex',              'agent',  'system', 'agent',   'coherence', 1440, 1500, 1800, NULL, FALSE),

    -- Les services d'entretien. Cadences serrées, seuils serrés : quand un
    -- cron de 5 minutes se tait 30 minutes, il est mort.
    ('arac-stale-closer',        'system', 'system', 'service', NULL, 60,    90,    180,   NULL, FALSE),
    ('arac-heartbeat-monitor',   'system', 'system', 'service', NULL, 5,     15,    30,    NULL, FALSE),
    ('arac-garbage-collector',   'system', 'system', 'service', NULL, 10080, 11000, 14400, NULL, FALSE),
    ('arac-backfill-embeddings', 'agent',  'system', 'service', NULL, 15,    45,    90,    NULL, FALSE)
ON CONFLICT (node_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- LES CONSTANTES DE RAISONNEMENT
--
-- Elles vivent en base, pas dans le code, pour une raison précise : les
-- ajuster ne doit pas demander un déploiement. Le cockpit les lit, vous
-- pouvez les changer par un UPDATE, et rejouer ce seed ne les écrasera pas.
--
-- `value` est du JSON : une chaîne s'écrit entre guillemets doubles, un nombre
-- nu.
-- ----------------------------------------------------------------------------
INSERT INTO arac.arac_config (key, value, description, updated_by) VALUES
    ('embedding_model',                  '"text-embedding-3-large"',
        'Le modele qui transforme un texte en vecteur. En changer invalide TOUS les vecteurs deja calcules : il faudrait tout recalculer, donc tout repayer.',
        'bootstrap'),
    ('embedding_dim',                    '3072',
        'Dimension du vecteur. DOIT correspondre exactement a la colonne SQL et au modele ci-dessus : une divergence ne leve aucune erreur, elle degrade le rappel en silence.',
        'bootstrap'),
    ('rrf_k',                            '60',
        'Constante de fusion RRF entre recherche lexicale et recherche vectorielle. Plus elle est grande, plus les deux classements sont traites a egalite.',
        'bootstrap'),
    ('search_default_limit',             '20',
        'Combien de souvenirs le rappel ramene quand personne ne precise.',
        'bootstrap'),
    ('stale_session_hours',              '24',
        'Une session ouverte plus longtemps est fermee automatiquement. Une session qui ne ferme jamais fausse toutes les mesures de duree.',
        'bootstrap'),
    ('agent_usefulness_min_pct',         '60',
        'Sous ce taux de validation, un agent produit plus de bruit que de savoir. Le cockpit le signale ; la decision de le couper reste la votre.',
        'bootstrap'),
    ('agent_usefulness_min_samples',     '30',
        'Nombre minimal de cas avant de juger un agent. Sans ce plancher, on condamne sur deux echecs de debut.',
        'bootstrap'),
    ('low_confidence_archive_threshold', '70',
        'Sous ce score (echelle 0-100), un atome part en archive basse confiance plutot que de polluer le rappel. Il n''est pas supprime : rien ne l''est jamais.',
        'bootstrap'),
    ('heartbeat_history_retention_days', '90',
        'Retention de l''historique des battements de coeur.',
        'bootstrap'),
    ('audit_log_retention_days',         '365',
        'Retention du journal d''audit : un an. C''est la memoire de ce que le cerveau a FAIT, distincte de ce qu''il SAIT.',
        'bootstrap')
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- ----------------------------------------------------------------------------
-- CONTRÔLE — ce que la base contient maintenant, et ce qui est armé.
-- ----------------------------------------------------------------------------
SELECT node_id, account, role, active,
       silent_warn_minutes AS alerte_min,
       silent_critical_minutes AS critique_min
  FROM arac.nodes
 ORDER BY active DESC, node_id;
