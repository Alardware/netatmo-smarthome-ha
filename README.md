# Netatmo Smart Home pour Home Assistant (non officiel)

Une seule intégration pour les appareils des trois applications Netatmo :

| Application | Appareils | Entités |
| --- | --- | --- |
| **Home + Control** | Volets Bubendorff (passerelle iDiamant), prises, interrupteurs, micromodules et variateurs Legrand Céliane / dooxie « with Netatmo », volets Legrand | `cover`, `switch`, `light`, puissance en W |
| **Home Coach** | Healthy Home Coach (Smart Indoor Air Quality Monitor) | température, humidité, CO2, bruit, pression, qualité de l'air |
| **Home Security** | Détecteur de fumée, détecteur de monoxyde de carbone | alarme fumée / CO, niveau de CO, dernier contact, signal Wi-Fi |

Pourquoi pas l'intégration officielle ?

- **Elle reste souvent muette après un redémarrage**, surtout connectée via « Home Assistant Cloud ».
  Ici, vous utilisez **votre propre application Netatmo**. Les jetons (qui changent à chaque
  renouvellement) sont gérés par le mécanisme standard de Home Assistant, qui les enregistre aussitôt.
  Un refus isolé de Netatmo ne déclenche pas de demande de reconnexion. Si Netatmo ne répond pas au
  démarrage, l'intégration réessaie toute seule.
- **Elle ignore les détecteurs de fumée et de CO.** Netatmo ne publie pas d'état d'alarme pour ces
  détecteurs, seulement des événements : cette intégration reconstruit l'alarme à partir de ces
  événements.
- **Elle limite ses requêtes** (Netatmo autorise environ 500 requêtes par heure) et fait une pause
  automatique si Netatmo signale « trop de requêtes ».

## 1. Créer votre application Netatmo (une seule fois)

1. Allez sur https://dev.netatmo.com/apps et connectez-vous avec votre compte Netatmo.
2. **Create** : donnez un nom (par exemple « Home Assistant »), une description, et votre nom et
   votre e-mail dans les champs « data protection officer ». Acceptez les conditions.
3. Dans l'application créée, **Redirect URI** : `https://my.home-assistant.io/redirect/oauth`.
   Laissez « Webhook URI » vide.
4. Notez le **client ID** et le **client secret**. Le secret est confidentiel : ne le partagez pas.

## 2. Installer l'intégration

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Alardware&repository=netatmo-smarthome-ha&category=integration)

1. HACS → menu ⋮ → *Dépôts personnalisés* → `https://github.com/Alardware/netatmo-smarthome-ha`,
   type *Intégration*. Ou cliquez sur le bouton ci-dessus.
2. Téléchargez « Netatmo Smart Home », puis redémarrez Home Assistant.

## 3. Configurer

1. Paramètres → Appareils et services → menu ⋮ → **Identifiants d'application** → **Ajouter** :
   choisissez « Netatmo Smart Home », puis collez le client ID et le client secret.
2. **Ajouter une intégration** → « Netatmo Smart Home » → connectez-vous à Netatmo et autorisez
   l'accès.
3. Vos appareils apparaissent, rangés par pièce comme dans les applications Netatmo.

L'intervalle de mise à jour (60 s par défaut) se règle dans les options de l'intégration.

**Une fois vos appareils vérifiés, désactivez l'intégration Netatmo officielle.** Les deux comptent
dans la même limite de requêtes Netatmo et feraient doublon.

## Détecteurs de fumée et de CO : à savoir

- L'alarme s'affiche au plus tard un cycle de mise à jour après l'événement (60 s par défaut).
- Netatmo ne fournit **pas le niveau de batterie** des détecteurs. Le capteur « Dernier contact »
  montre leur dernier échange avec Netatmo (environ une fois par mois, lors du test automatique).
- Elle s'éteint avec l'événement « fin d'alarme » de Netatmo, ou d'elle-même 30 minutes après une
  détection jamais suivie de cet événement.
- Après un redémarrage, une alarme des 30 dernières minutes est retrouvée dans l'historique.
- **La sirène des détecteurs et les notifications de l'application Netatmo restent votre vraie
  protection.** Home Assistant vient en plus.

## En cas de problème

- Journaux : Paramètres → Système → Journaux, cherchez `netatmo_smarthome`.
- Diagnostics : la page de l'intégration → ⋮ → **Télécharger les diagnostics**. Les réponses brutes
  de Netatmo y figurent, sans jetons ni e-mail ni localisation. Joignez-les à un
  [ticket](https://github.com/Alardware/netatmo-smarthome-ha/issues).

**État du projet :** le format des réponses de Netatmo provient de projets communautaires (pyatmo,
gladys-netatmo, gladys-legrand-home-control). Il n'a pas encore été vérifié sur toutes les
installations réelles, en particulier pour les détecteurs et les volets positionnables. Les
diagnostics de vos appareils aident à corriger.

## Crédits

- [pyatmo](https://github.com/jabesq/pyatmo) (MIT) : référence des types d'appareils et des
  points d'accès de l'API.
- [gladys-netatmo](https://github.com/Terdious/gladys-netatmo) et
  [gladys-legrand-home-control](https://github.com/LM1LC3N7/gladys-legrand-home-control)
  (Apache-2.0) : comportement des alarmes, des volets Bubendorff et des erreurs de l'API. Aucun code
  n'en est copié.

Netatmo, Legrand et Bubendorff sont des marques de leurs propriétaires respectifs. Ce projet n'est
affilié à aucune d'elles.

## Développement

```bash
pip install pytest-homeassistant-custom-component
pytest
```
