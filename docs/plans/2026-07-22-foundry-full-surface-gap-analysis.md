---
title: Foundry full-surface endpoint catalog + pltr-cli gap analysis
type: analysis
status: draft
date: 2026-07-22
target_repo: pltr-cli
---

# Foundry Full-Surface Gap Analysis

Complete catalog of every known Foundry API endpoint — public `/api/v2`, undocumented
internal Conjure services, and the internal GraphQL gateway — mapped against what
`pltr-cli` implements today, with a prioritized addition list.

## Provenance

| Source | What it contributed |
|---|---|
| `@palantir/mcp` v0.397.0 sourcemap (`~/.npm/_npx/63a3fbe1b43eb419/node_modules/@palantir/mcp/dist/index.mjs.map`, still on disk 2026-07-22) | **832 endpoints / 27 Conjure services**, extracted mechanically from `bridge.call("<Service>", "<endpoint>", "<verb>", "<path>", …)` sites in the generated clients. Endpoint paths were *read*, not guessed. |
| Brain `concepts/engineering/foundry-internal-api/*` (9 docs) + lesson `foundry-internal-api-reverse-indexes-2026-07-21` | Live-verification status of ~120 endpoints, live-verified against `zap.usw-18.palantirfoundry.com` 2026-07-21/22 (~2,000 read-only calls). Every claim VERIFIED unless marked otherwise. |
| Brain `concepts/projects/pltr-cli-internal-api-dependency` | Shipped/planned status of the `pltr dependency` internal-API slices (Phases A + B through PR #11). |
| Frontend-bundle harvesting (hubble + 5 other app shells, per `platform-sweep`) | 3,010 GraphQL definitions, 22 app-shell inventory, 4 monocle **V3** endpoints absent from the MCP sourcemap, GraphQL `Mutation` root contents. |
| `src/pltr/cli.py`, `src/pltr/services/foundry_internal_client.py`, `src/pltr/services/dependency_internal_specs.py`, `docs/capabilities/foundry-agent-capabilities.json` (73 rows: 4 implemented / 67 planned / 2 blocked) | Current pltr-cli coverage. |

**Scope rule (repo + brain):** pltr-cli consumes these internal APIs **read-only**.
`PUT`/`POST` is not a mutation signal in Conjure (66 read-PUTs, ~220 read-POSTs exist) —
classification is by Conjure method-name token. All empty/truncated/permission-filtered
results must surface as *inconclusive*, never "safe" (fail toward false safety).

Conjure base-path convention (verified for every mounted service): `https://<stack>/<service-name>/api`.
Deviation found: `foundry-datahealth` mounts at **`/data-health/api`**.

---

## 1. Full endpoint catalog

### 1a. Internal Conjure services (836 rows; 832 from MCP sourcemap + 4 frontend-harvested monocle V3)

`verified (brain)` column values:

- `VERIFIED` — executed live 2026-07-21/22, real response captured.
- `partial (…)` — mounted/shape probed, populated response not confirmed.
- `contract-only` — request contract proven, response never observed (no live fixture).
- `unresolved` — attempted and not cracked (details in brain doc §UNRESOLVED).
- `catalog (sourcemap only)` — path/verb/name read from `@palantir/mcp` v0.397.0; never live-exercised. Treat as **UNVERIFIED**.

`pltr-cli status` column values: `internal-only via <command>` = reachable today through the
internal client; `spec registered` = `dependency_internal_specs.py` entry exists; `planned` =
named in an active plan; `not implemented` = no code path.

Note the MCP extraction contains **no GraphQL**, no `/api/v2` public routes, and no monocle V3
(the V3 generation was harvested from the shipped Data Lineage frontend instead — V2 is dead
client code: zero call sites in 68 bundles; **target V3**).


#### `compass` (153 endpoints; base `/compass/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `aggregateByField` | POST `/aggregate-field` | catalog (sourcemap only) | not implemented |
| `getAllResources` | GET `/all-resources` | catalog (sourcemap only) | not implemented |
| `getAutosaveLocation` | GET `/autosave` | catalog (sourcemap only) | not implemented |
| `saveAutosaveResource` | POST `/autosaves/save/{rid}` | catalog (sourcemap only) | not implemented |
| `putAutosaveResource` | PUT `/autosaves/{rid}` | catalog (sourcemap only) | not implemented |
| `batchGetChildrenByName` | POST `/batch/folders/children-by-name` | catalog (sourcemap only) | not implemented |
| `getHomeFoldersForUsers` | POST `/batch/folders/home` | catalog (sourcemap only) | not implemented |
| `getHomeFoldersMetadata` | POST `/batch/folders/home/metadata` | catalog (sourcemap only) | not implemented |
| `getOrganizations` | POST `/batch/hierarchy/organizations` | catalog (sourcemap only) | not implemented |
| `getOrganizationAndProjectInfos` | POST `/batch/hierarchy/projects` | catalog (sourcemap only) | not implemented |
| `getDecoratedOrganizationAndProjectInfos` | POST `/batch/hierarchy/projects/decorated` | catalog (sourcemap only) | not implemented |
| `getPaths` | POST `/batch/paths` | catalog (sourcemap only) | not implemented |
| `getFileSystemIdsForProjects` | POST `/batch/projectFileSystemId` | catalog (sourcemap only) | not implemented |
| `getProjects` | POST `/batch/projects-by-rids` | catalog (sourcemap only) | not implemented |
| `getResources` | POST `/batch/resources` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `getResourcesByPaths` | POST `/batch/resources-by-paths` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `batchGetAncestors` | POST `/batch/resources/ancestors` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `resourcesExist` | POST `/batch/resources/exist` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `removeResourcesFromProjectPreview` | PUT `/batch/resources/make-non-preview` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `addResourcesToProjectPreview` | PUT `/batch/resources/make-preview` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `batchGetParents` | POST `/batch/resources/parents` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `batchPutResource` | PUT `/batch/resources/put` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `indexMetadatas` | POST `/batch/search/{bucket}` | catalog (sourcemap only) | not implemented |
| `getTemplates` | PUT `/batch/templates` | catalog (sourcemap only) | not implemented |
| `getTemplatesV2` | PUT `/batch/templates/v2` | catalog (sourcemap only) | not implemented |
| `addToTrash` | POST `/batch/trash/add` | catalog (sourcemap only) | not implemented |
| `restore` | POST `/batch/trash/restore` | catalog (sourcemap only) | not implemented |
| `addServiceProjectResourcesToTrash` | POST `/batch/trash/service-projects/add` | catalog (sourcemap only) | not implemented |
| `restoreServiceProjectResources` | POST `/batch/trash/service-projects/restore` | catalog (sourcemap only) | not implemented |
| `getBranchesForResources` | PUT `/branches-for-resources` | VERIFIED (empty on fixtures) | not implemented |
| `deleteProjectContactInformation` | DELETE `/contact-information/{projectRid}` | catalog (sourcemap only) | not implemented |
| `setProjectContactInformation` | PUT `/contact-information/{projectRid}` | catalog (sourcemap only) | not implemented |
| `convertExistingProjects` | POST `/convertExistingProjects` | catalog (sourcemap only) | not implemented |
| `deleteFavorites` | DELETE `/favorites` | catalog (sourcemap only) | not implemented |
| `getFavorites` | GET `/favorites` | catalog (sourcemap only) | not implemented |
| `addFavorites` | POST `/favorites` | catalog (sourcemap only) | not implemented |
| `isFavoritesMigrated` | GET `/favorites-migrated` | catalog (sourcemap only) | not implemented |
| `markFavoritesAsMigrated` | POST `/favorites-migrated` | catalog (sourcemap only) | not implemented |
| `createFolder` | POST `/folders` | catalog (sourcemap only) | not implemented |
| `createFolderAllowingHidden` | POST `/folders-allowing-hidden` | catalog (sourcemap only) | not implemented |
| `getHomeFolder` | GET `/folders/home` | catalog (sourcemap only) | not implemented |
| `getHomeFolderV2` | GET `/folders/home/v2` | catalog (sourcemap only) | not implemented |
| `moveResources` | POST `/folders/{folderRid}/children` | catalog (sourcemap only) | not implemented |
| `getAllChildrenRids` | GET `/folders/{rid}/all-children-rids` | catalog (sourcemap only) | not implemented |
| `getChildren` | GET `/folders/{rid}/children` | catalog (sourcemap only) | not implemented |
| `getAllNamespaceProjectRids` | GET `/hierarchy/namespaces/{namespaceRid}/project-rids` | catalog (sourcemap only) | not implemented |
| `getOrganizationRids` | GET `/hierarchy/organization-rids` | catalog (sourcemap only) | not implemented |
| `getAllOrganizations` | GET `/hierarchy/organizations` | catalog (sourcemap only) | not implemented |
| `createOrganization` | POST `/hierarchy/organizations` | catalog (sourcemap only) | not implemented |
| `getOrganizationsAndProjects` | GET `/hierarchy/organizations/all-projects` | catalog (sourcemap only) | not implemented |
| `getOrganization` | GET `/hierarchy/organizations/{rid}` | catalog (sourcemap only) | not implemented |
| `updateOrganization` | POST `/hierarchy/organizations/{rid}` | catalog (sourcemap only) | not implemented |
| `getOrganizationProjectRids` | GET `/hierarchy/organizations/{rid}/project-rids` | catalog (sourcemap only) | not implemented |
| `getOrganizationProjects` | GET `/hierarchy/organizations/{rid}/projects` | catalog (sourcemap only) | not implemented |
| `createProject` | POST `/hierarchy/projects` | catalog (sourcemap only) | not implemented |
| `getFavoriteProjects` | GET `/hierarchy/projects/favorites` | catalog (sourcemap only) | not implemented |
| `getFavoriteProjectRids` | GET `/hierarchy/projects/favorites-rids` | catalog (sourcemap only) | not implemented |
| `getProjectScopeFromResources` | POST `/hierarchy/projects/scope` | catalog (sourcemap only) | not implemented |
| `getProjectImports` | GET `/hierarchy/projects/{projectRid}/imports` | catalog (sourcemap only) | not implemented |
| `importResource` | POST `/hierarchy/projects/{projectRid}/imports` | catalog (sourcemap only) | not implemented |
| `getProjectScope` | GET `/hierarchy/projects/{projectRid}/scope` | catalog (sourcemap only) | not implemented |
| `getProject` | GET `/hierarchy/projects/{rid}` | catalog (sourcemap only) | not implemented |
| `updateProject` | POST `/hierarchy/projects/{rid}` | catalog (sourcemap only) | not implemented |
| `getOrganizationAndProjectInfo` | GET `/hierarchy/resources/{rid}/project` | catalog (sourcemap only) | not implemented |
| `createServiceProject` | POST `/hierarchy/service-projects` | catalog (sourcemap only) | not implemented |
| `updateServiceProject` | POST `/hierarchy/service-projects/{rid}` | catalog (sourcemap only) | not implemented |
| `getAllNamespaceRids` | GET `/hierarchy/v2/all-namespace-rids` | catalog (sourcemap only) | not implemented |
| `getNamespaceRidsByMavenGroups` | POST `/hierarchy/v2/batch/namespace-rids-by-maven-group` | catalog (sourcemap only) | not implemented |
| `getNamespaceMavenGroupPrefixesForEnrollments` | POST `/hierarchy/v2/batch/namespace/maven-group-prefix-for-enrollments` | catalog (sourcemap only) | not implemented |
| `getNamespaces` | PUT `/hierarchy/v2/batch/namespaces` | catalog (sourcemap only) | not implemented |
| `getNamespaceQuotaForEnrollments` | PUT `/hierarchy/v2/batch/namespaces/quota` | catalog (sourcemap only) | not implemented |
| `getNamespaceRidsForResources` | PUT `/hierarchy/v2/batch/namespaces/resources` | catalog (sourcemap only) | not implemented |
| `getProjects` | PUT `/hierarchy/v2/batch/projects` | catalog (sourcemap only) | not implemented |
| `getProjectsV3` | PUT `/hierarchy/v2/batch/projects-v3` | catalog (sourcemap only) | not implemented |
| `getOwningEnrollmentRidsForResources` | PUT `/hierarchy/v2/batch/resources/enrollments` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `getProjectRidsForResources` | PUT `/hierarchy/v2/batch/resources/projects` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `generateProjectRid` | POST `/hierarchy/v2/generate-project-rid` | catalog (sourcemap only) | not implemented |
| `createNamespace` | POST `/hierarchy/v2/namespaces` | catalog (sourcemap only) | not implemented |
| `createNamespaceInEnrollment` | POST `/hierarchy/v2/namespaces-in-enrollment` | catalog (sourcemap only) | not implemented |
| `updateNamespace` | PUT `/hierarchy/v2/namespaces/{rid}` | catalog (sourcemap only) | not implemented |
| `setNamespaceFileSystem` | PUT `/hierarchy/v2/namespaces/{rid}/fileSystemId` | catalog (sourcemap only) | not implemented |
| `updateProjectAccessRequestConfiguration` | PUT `/hierarchy/v2/project-access-request-configuration/{projectRid}` | catalog (sourcemap only) | not implemented |
| `createProject` | POST `/hierarchy/v2/projects` | catalog (sourcemap only) | not implemented |
| `createProjectFromTemplate` | POST `/hierarchy/v2/projects-from-template` | catalog (sourcemap only) | not implemented |
| `getAllConjunctiveMarkingsInProject` | GET `/hierarchy/v2/projects/{projectRid}/all-conjunctive-markings` | catalog (sourcemap only) | not implemented |
| `updateProject` | PUT `/hierarchy/v2/projects/{rid}` | catalog (sourcemap only) | not implemented |
| `removeDeletedOrganizationMarkings` | PUT `/hierarchy/v2/projects/{rid}/remove-deleted-organization-markings` | catalog (sourcemap only) | not implemented |
| `getAllPrincipalsWithRoleOnResources` | POST `/hierarchy/v2/roles/all` | catalog (sourcemap only) | not implemented |
| `getEffectiveRoleGrants` | PUT `/hierarchy/v2/roles/effective/grants` | catalog (sourcemap only) | not implemented |
| `getEffectiveRolesForPrincipals` | PUT `/hierarchy/v2/roles/effective/principals` | catalog (sourcemap only) | not implemented |
| `createServiceProject` | POST `/hierarchy/v2/service-projects` | catalog (sourcemap only) | not implemented |
| `updateServiceProject` | PUT `/hierarchy/v2/service-projects/{rid}` | catalog (sourcemap only) | not implemented |
| `updateResourceMarkings` | POST `/markings/{rid}` | catalog (sourcemap only) | not implemented |
| `resolvePath` | GET `/paths` | catalog (sourcemap only) | not implemented |
| `createPath` | PUT `/paths` | catalog (sourcemap only) | not implemented |
| `getProjectPreviewResources` | PUT `/project-preview-resources.` | catalog (sourcemap only) | not implemented |
| `getImportingProjectsForResources` | POST `/projects/imports/importing-projects` | VERIFIED | not implemented |
| `getRepresentativeProjectContentRids` | POST `/projects/imports/project-content-root-rids` | catalog (sourcemap only) | not implemented |
| `getImports` | POST `/projects/imports/{projectRid}` | unresolved (wrapper field unknown) | not implemented |
| `canImportResources` | PUT `/projects/imports/{projectRid}/can-import` | unresolved (wrapper field unknown) | not implemented |
| `getResourceContexts` | POST `/projects/imports/{projectRid}/context` | VERIFIED | not implemented |
| `removeImports` | DELETE `/projects/imports/{projectRid}/import` | unresolved (wrapper field unknown) | not implemented |
| `importResources` | POST `/projects/imports/{projectRid}/import` | unresolved (wrapper field unknown) | not implemented |
| `getImportRids` | POST `/projects/imports/{projectRid}/rids` | VERIFIED | not implemented |
| `removeImportsFromServiceProject` | DELETE `/projects/imports/{projectRid}/service-projects/import` | unresolved (wrapper field unknown) | not implemented |
| `importResourcesToServiceProject` | POST `/projects/imports/{projectRid}/service-projects/import` | unresolved (wrapper field unknown) | not implemented |
| `getActions` | GET `/registry/actions` | catalog (sourcemap only) | not implemented |
| `getApplications` | GET `/registry/applications` | catalog (sourcemap only) | not implemented |
| `getDefaultBranchName` | GET `/registry/default-branch-name-json` | catalog (sourcemap only) | not implemented |
| `getResourceByPath` | GET `/resources` | catalog (sourcemap only) | not implemented |
| `postResource` | POST `/resources` | catalog (sourcemap only) | not implemented |
| `putServiceProjectResourceAllowingHidden` | PUT `/resources-allowing-hidden/service-projects/{rid}` | catalog (sourcemap only) | not implemented |
| `putResourceAllowingHidden` | PUT `/resources-allowing-hidden/{rid}` | catalog (sourcemap only) | not implemented |
| `createResourceFrom` | POST `/resources/create-from/{rid}` | catalog (sourcemap only) | not implemented |
| `putServiceProjectResource` | PUT `/resources/service-projects/{rid}` | catalog (sourcemap only) | not implemented |
| `checkName` | POST `/resources/{parentRid}/checkName` | catalog (sourcemap only) | not implemented |
| `checkNames` | POST `/resources/{parentRid}/checkNames` | catalog (sourcemap only) | not implemented |
| `getResource` | GET `/resources/{rid}` | catalog (sourcemap only) | not implemented |
| `putResource` | PUT `/resources/{rid}` | catalog (sourcemap only) | not implemented |
| `getAncestors` | GET `/resources/{rid}/ancestors` | catalog (sourcemap only) | not implemented |
| `setName` | POST `/resources/{rid}/name` | catalog (sourcemap only) | not implemented |
| `getParent` | GET `/resources/{rid}/parent` | catalog (sourcemap only) | not implemented |
| `getPath` | GET `/resources/{rid}/path-json` | catalog (sourcemap only) | not implemented |
| `touch` | POST `/resources/{rid}/touch` | catalog (sourcemap only) | not implemented |
| `getResourceRoleSets` | PUT `/roleSets` | catalog (sourcemap only) | not implemented |
| `getResourceRoles` | POST `/roles` | catalog (sourcemap only) | not implemented |
| `updateServiceProjectResourceRoles` | POST `/roles/service-projects/{rid}` | catalog (sourcemap only) | not implemented |
| `updateResourcesRoles` | POST `/roles/v2/bulk` | catalog (sourcemap only) | not implemented |
| `updateResourceRolesV2` | POST `/roles/v2/{rid}` | catalog (sourcemap only) | not implemented |
| `updateResourceRoles` | POST `/roles/{rid}` | catalog (sourcemap only) | not implemented |
| `removeAllDisableInheritedPermissions` | POST `/roles/{rid}/remove-disable-inherited-permissions` | catalog (sourcemap only) | not implemented |
| `search` | POST `/search` | catalog (sourcemap only) | not implemented |
| `searchProjects` | POST `/search/projects` | catalog (sourcemap only) | not implemented |
| `indexMetadata` | POST `/search/{rid}/{bucket}` | catalog (sourcemap only) | not implemented |
| `saveSearchTextInHistory` | POST `/searchTextHistory` | catalog (sourcemap only) | not implemented |
| `createTemplate` | POST `/templates` | catalog (sourcemap only) | not implemented |
| `getAllProjectTemplatesForNamespace` | GET `/templates/namespace/{namespaceRid}` | catalog (sourcemap only) | not implemented |
| `deleteTemplate` | DELETE `/templates/{templateRid}` | catalog (sourcemap only) | not implemented |
| `updateTemplate` | POST `/templates/{templateRid}` | catalog (sourcemap only) | not implemented |
| `getTimestampedFavorites` | GET `/timestamped-favorites` | catalog (sourcemap only) | not implemented |
| `areTrackedPermanentlyDeletedRids` | PUT `/trash/are-tracked-permanently-deleted-rids` | catalog (sourcemap only) | not implemented |
| `deletePermanently` | POST `/trash/delete` | catalog (sourcemap only) | not implemented |
| `registerNamespacesForDeletion` | POST `/trash/register-namespaces-for-deletion` | catalog (sourcemap only) | not implemented |
| `registerProjectsForDeletion` | POST `/trash/register-projects-for-deletion` | catalog (sourcemap only) | not implemented |
| `deleteServiceProjectResourcesPermanently` | POST `/trash/service-projects/delete` | catalog (sourcemap only) | not implemented |
| `unregisterNamespacesForDeletion` | POST `/trash/unregister-namespaces-for-deletion` | catalog (sourcemap only) | not implemented |
| `unregisterProjectsForDeletion` | POST `/trash/unregister-projects-for-deletion` | catalog (sourcemap only) | not implemented |
| `getPermanentlyDeletedProjects` | GET `/trash/{namespaceRid}/permanently-deleted-projects` | catalog (sourcemap only) | not implemented |
| `getPermanentlyDeletedRids` | GET `/trash/{projectRid}/permanently-deleted-rids` | catalog (sourcemap only) | not implemented |
| `registerProjectForDeletion` | PUT `/trash/{projectRid}/register-for-deletion` | catalog (sourcemap only) | not implemented |
| `unregisterProjectForDeletion` | PUT `/trash/{projectRid}/unregister-for-deletion` | catalog (sourcemap only) | not implemented |
| `getResourceLocations` | POST `/ui/batch/resources/location` | partial (shape/mount only) (body shape UNVERIFIED) | not implemented |
| `getResourceLocation` | GET `/ui/resources/{rid}/location` | catalog (sourcemap only) | not implemented |

#### `ontology-metadata` (65 endpoints; base `/ontology-metadata/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `bulkLoadOntologyBranches` | POST `/ontology/branch/bulk-load` | catalog (sourcemap only) | not implemented |
| `getOntologyBranchRid` | GET `/ontology/branch/global/{globalBranchRid}` | catalog (sourcemap only) | not implemented |
| `loadOntologyBranchForProposal` | POST `/ontology/branch/load/proposalV2/{ontologyProposalRid}` | catalog (sourcemap only) | not implemented |
| `loadOntologyBranchByVersion` | POST `/ontology/branch/load/version` | catalog (sourcemap only) | not implemented |
| `loadOntologyBranch` | POST `/ontology/branch/load/{ontologyBranchRid}` | catalog (sourcemap only) | not implemented |
| `loadOntologyBranchMarkings` | POST `/ontology/branch/load/{ontologyBranchRid}/markings` | catalog (sourcemap only) | not implemented |
| `createOntologyServiceBranch` | PUT `/ontology/branch/service-branch/create/{ontologyRid}` | catalog (sourcemap only) | not implemented |
| `mergeOntologyServiceBranch` | PUT `/ontology/branch/service-branch/merge/{ontologyBranchRid}` | catalog (sourcemap only) | not implemented |
| `setOntologyBranchOrganizationMarkings` | PUT `/ontology/branch/setBranchOrganizationMarkings` | catalog (sourcemap only) | not implemented |
| `setOntologyBranchLock` | PUT `/ontology/branch/setLock/{ontologyBranchRid}` | catalog (sourcemap only) | not implemented |
| `discardChangesOnBranchV2` | POST `/ontology/branch/{ontologyBranchRid}/discardChangesV2` | catalog (sourcemap only) | not implemented |
| `findConflicts` | POST `/ontology/branch/{ontologyBranchRid}/findConflicts` | partial (shape/mount only) (reachable; 400 on empty body) | not implemented |
| `dryRunMergeOntologyBranch` | POST `/ontology/branch/{ontologyBranchRid}/merge/dry-run` | partial (shape/mount only) (reachable; 400 on empty body) | not implemented |
| `validateOntologyBranch` | POST `/ontology/branch/{ontologyBranchRid}/validate` | partial (shape/mount only) (reachable; 400 on empty body) | not implemented |
| `createOntologyBranch` | POST `/ontology/branch/{ontologyRid}/createBranch` | catalog (sourcemap only) | not implemented |
| `discardChangesOnBranch` | POST `/ontology/branch/{ontologyRid}/{ontologyBranchRid}/discardChanges` | catalog (sourcemap only) | not implemented |
| `getEntityDelegateDataset` | POST `/ontology/entityDelegateDataset` | catalog (sourcemap only) | not implemented |
| `getEntityQueryableSource` | POST `/ontology/entityQueryableSource` | catalog (sourcemap only) | not implemented |
| `getFeatureConfigurations` | GET `/ontology/featureConfigurations` | catalog (sourcemap only) | not implemented |
| `getLinkMetadataForObjectTypes` | POST `/ontology/getLinkMetadataForObjectTypes` | VERIFIED | not implemented |
| `getLinkTypesForObjectTypes` | POST `/ontology/linkTypesForObjectTypes` | VERIFIED | not implemented |
| `getActionTypesForInterfaceType` | PUT `/ontology/ontology/actionTypesForInterfaceType` | catalog (sourcemap only) | not implemented |
| `getActionTypesForObjectType` | PUT `/ontology/ontology/actionTypesForObjectType` | VERIFIED | planned (dependency Phase B/C) |
| `bulkLoadOntologyEntities` | POST `/ontology/ontology/bulkLoadEntities` | catalog (sourcemap only) | not implemented |
| `bulkLoadOntologyEntitiesByDatasources` | POST `/ontology/ontology/bulkLoadEntitiesByDatasources` | VERIFIED | not implemented |
| `getOntologyRidsForEntities` | POST `/ontology/ontology/getOntologyRidsForEntities` | catalog (sourcemap only) | not implemented |
| `loadOntology` | POST `/ontology/ontology/load` | catalog (sourcemap only) | not implemented |
| `loadAllOntology` | POST `/ontology/ontology/load/all` | catalog (sourcemap only) | not implemented |
| `loadAllOntologyEntities` | POST `/ontology/ontology/load/allEntities` | catalog (sourcemap only) | not implemented |
| `loadOntologyDatasources` | POST `/ontology/ontology/load/datasources` | catalog (sourcemap only) | not implemented |
| `getOntologyEntitiesForTypeGroups` | PUT `/ontology/ontology/load/entitiesForTypeGroups` | catalog (sourcemap only) | not implemented |
| `loadAllObjectTypesFromOntologyPage` | POST `/ontology/ontology/load/loadAllObjectTypes` | catalog (sourcemap only) | not implemented |
| `getObjectTypesForInterfaceTypes` | PUT `/ontology/ontology/load/objectTypesForInterfaceTypes` | catalog (sourcemap only) | not implemented |
| `getObjectTypesForSharedPropertyTypes` | PUT `/ontology/ontology/load/objectTypesForSharedPropertyTypes` | schema-proven (no SPT data on stack) | not implemented |
| `getObjectTypesForTypeGroups` | PUT `/ontology/ontology/load/objectTypesForTypeGroups` | catalog (sourcemap only) | not implemented |
| `getOntologySummary` | POST `/ontology/ontology/load/{ontologyRid}/summary` | catalog (sourcemap only) | not implemented |
| `loadAllInterfaceTypesFromOntology` | PUT `/ontology/ontology/load/{ontologyRid}/{ontologyVersion}/loadAllInterfaceTypes` | catalog (sourcemap only) | not implemented |
| `loadAllObjectTypesFromOntology` | POST `/ontology/ontology/load/{ontologyRid}/{ontologyVersion}/loadAllObjectTypes` | catalog (sourcemap only) | not implemented |
| `loadAllSharedPropertyTypesFromOntology` | PUT `/ontology/ontology/load/{ontologyRid}/{ontologyVersion}/loadAllSharedPropertyTypes` | VERIFIED (empty list) | not implemented |
| `loadAllTypeGroupsFromOntology` | PUT `/ontology/ontology/load/{ontologyRid}/{ontologyVersion}/loadAllTypeGroups` | catalog (sourcemap only) | not implemented |
| `loadOntologyEntities` | POST `/ontology/ontology/loadEntities` | catalog (sourcemap only) | not implemented |
| `modifyOntology` | POST `/ontology/ontology/modify` | catalog (sourcemap only) | not implemented |
| `loadAllOntologies` | POST `/ontology/ontology/ontologies/load/all` | VERIFIED | not implemented |
| `getOrganizationRidsForOntology` | GET `/ontology/ontology/{ontologyRid}/organizationRids` | catalog (sourcemap only) | not implemented |
| `getRelationsForObjectTypes` | POST `/ontology/relationsForObjectTypes` | VERIFIED | not implemented |
| `getObjectTypeSemanticSearchStatus` | GET `/ontology/search/v0/objectTypeSemanticSearchStatus` | catalog (sourcemap only) | not implemented |
| `objectTypes` | POST `/ontology/search/v0/objectTypes` | catalog (sourcemap only) | not implemented |
| `searchActionTypes` | POST `/ontology/search/v0/searchActionTypes` | catalog (sourcemap only) | not implemented |
| `searchInterfaceTypes` | POST `/ontology/search/v0/searchInterfaceTypes` | catalog (sourcemap only) | not implemented |
| `searchLinkTypes` | POST `/ontology/search/v0/searchLinkTypes` | catalog (sourcemap only) | not implemented |
| `searchObjectTypes` | POST `/ontology/search/v0/searchObjectTypes` | catalog (sourcemap only) | not implemented |
| `searchSharedPropertyTypes` | POST `/ontology/search/v0/searchSharedPropertyTypes` | catalog (sourcemap only) | not implemented |
| `searchTypeGroups` | POST `/ontology/search/v0/searchTypeGroups` | catalog (sourcemap only) | not implemented |
| `createOntology` | POST `/ontology/v2/create` | catalog (sourcemap only) | not implemented |
| `deleteOntology` | POST `/ontology/v2/delete/{ontologyRid}` | catalog (sourcemap only) | not implemented |
| `loadAllOntologiesInternal` | POST `/ontology/v2/load/all` | catalog (sourcemap only) | not implemented |
| `getEntityModificationHistoryV2` | POST `/ontology/v2/modification/history/entity` | catalog (sourcemap only) | not implemented |
| `modifyOntology` | POST `/ontology/v2/modify` | catalog (sourcemap only) | not implemented |
| `dryRunModifyOntology` | POST `/ontology/v2/modify/dry-run` | partial (shape/mount only) (reachable; 400 on empty body) | not implemented |
| `updateOntology` | POST `/ontology/v2/update/{ontologyRid}` | catalog (sourcemap only) | not implemented |
| `getModifiedEntities` | POST `/ontology/v2/{ontologyRid}/diff` | partial (shape/mount only) (reachable; 400 on empty body) | not implemented |
| `importSharedPropertyTypes` | POST `/ontology/v2/{ontologyRid}/import` | catalog (sourcemap only) | not implemented |
| `checkExistingUniqueIdentifiers` | POST `/ontology/v2/{ontologyRid}/modification/check-uniqueness` | catalog (sourcemap only) | not implemented |
| `getModificationHistory` | POST `/ontology/v2/{ontologyRid}/modification/history` | catalog (sourcemap only) | not implemented |
| `getEntityModificationHistory` | POST `/ontology/v2/{ontologyRid}/modification/history/entity` | catalog (sourcemap only) | not implemented |

#### `build2` (68 endpoints; base `/build2/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getBuildGroupReport` | GET `/info/build-groups/{buildGroupRid}` | catalog (sourcemap only) | not implemented |
| `getBuildReports` | POST `/info/builds` | catalog (sourcemap only) | not implemented |
| `getDecoratedBuildReport` | POST `/info/builds/decorated` | catalog (sourcemap only) | not implemented |
| `getBuildReportDeprecated` | GET `/info/builds/{buildRid}` | catalog (sourcemap only) | not implemented |
| `getBuildReport` | GET `/info/builds2/{buildRid}` | catalog (sourcemap only) | not implemented |
| `getEvents` | POST `/info/events` | catalog (sourcemap only) | not implemented |
| `getLatestEventOffset` | GET `/info/events/offset` | catalog (sourcemap only) | not implemented |
| `getBuildGroupReports` | POST `/info/groups` | catalog (sourcemap only) | not implemented |
| `getJobReportsDeprecated` | POST `/info/jobs` | catalog (sourcemap only) | not implemented |
| `getDecoratedJobReport` | POST `/info/jobs/decorated` | catalog (sourcemap only) | not implemented |
| `getJobReportDeprecated` | GET `/info/jobs/{jobRid}` | catalog (sourcemap only) | not implemented |
| `canViewJobReport` | GET `/info/jobs/{jobRid}/can-view-report` | catalog (sourcemap only) | not implemented |
| `getJobReportsDeprecated2` | POST `/info/jobs2` | catalog (sourcemap only) | not implemented |
| `getJobReportDeprecated2` | GET `/info/jobs2/{jobRid}` | catalog (sourcemap only) | not implemented |
| `getJobReports` | POST `/info/jobs3` | catalog (sourcemap only) | not implemented |
| `getRunReportsForJobs` | POST `/info/jobs3/runs` | catalog (sourcemap only) | not implemented |
| `getJobReport` | GET `/info/jobs3/{jobRid}` | catalog (sourcemap only) | not implemented |
| `getRunReportsForJob` | GET `/info/jobs3/{jobRid}/runs` | catalog (sourcemap only) | not implemented |
| `getJobQueues` | POST `/info/queues` | catalog (sourcemap only) | not implemented |
| `getConnectingJobSpecNodes` | POST `/jobspecs/branches/{branch}/connecting-jobspec-nodes` | unresolved (always []) | not implemented |
| `getConnectingJobSpecs` | POST `/jobspecs/branches/{branch}/connecting-jobspecs` | VERIFIED | not implemented |
| `getDownstreamJobSpecs` | POST `/jobspecs/branches/{branch}/downstream-jobspecs` | VERIFIED | spec registered (ACP-02); collector wiring in progress |
| `getDownstreamJobSpecNodes` | POST `/jobspecs/branches/{branch}/downstream-jobspecs-nodes` | unresolved (always []) | not implemented |
| `getUpstreamJobSpecNodes` | POST `/jobspecs/branches/{branch}/upstream-jobspec-nodes` | unresolved (always []) | not implemented |
| `getUpstreamJobSpecs` | POST `/jobspecs/branches/{branch}/upstream-jobspecs` | VERIFIED | spec registered (ACP-02); collector wiring in progress |
| `canEditJobSpecsWithWorker` | POST `/jobspecs/can-edit-jobspecs-with-workers` | catalog (sourcemap only) | not implemented |
| `canPutJobSpecs` | POST `/jobspecs/can-put-jobspecs` | catalog (sourcemap only) | not implemented |
| `canRemoveJobSpecs` | POST `/jobspecs/can-remove-jobspecs` | catalog (sourcemap only) | not implemented |
| `canRunJobSpecs` | POST `/jobspecs/can-run-jobspecs` | catalog (sourcemap only) | not implemented |
| `getJobSpecsForDatasetInGraph` | GET `/jobspecs/datasets/{datasetRid}` | VERIFIED | internal-only via `pltr dependency` (ACP-01) |
| `getEvents` | POST `/jobspecs/events` | 403 service-root perm | not implemented |
| `getLatestEventOffset` | GET `/jobspecs/events/offset` | 403 service-root perm | not implemented |
| `getBranches` | POST `/jobspecs/get-branches` | unresolved (2nd required field unknown) | not implemented |
| `getJobSpec` | GET `/jobspecs/get-historical-jobspec/{jobSpecRid}` | catalog (sourcemap only) | not implemented |
| `getJobSpecs` | POST `/jobspecs/get-historical-jobspecs` | catalog (sourcemap only) | not implemented |
| `getJobSpecForDatasetInGraph` | POST `/jobspecs/get-jobspec-for-dataset` | catalog (sourcemap only) | not implemented |
| `getJobSpecsInGraph` | POST `/jobspecs/get-jobspecs` | catalog (sourcemap only) | not implemented |
| `getJobSpecsForDatasetsInGraph` | POST `/jobspecs/get-jobspecs-for-datasets` | VERIFIED | not implemented |
| `getJobSpecsForDatasetsAndBranchesInGraph` | POST `/jobspecs/get-jobspecs-for-datasets-and-branches` | VERIFIED | not implemented |
| `hasJobSpecWithSever` | POST `/jobspecs/has-job-spec-with-sever` | catalog (sourcemap only) | not implemented |
| `putJobSpecs` | POST `/jobspecs/put-jobspecs` | catalog (sourcemap only) | not implemented |
| `putJobSpecsOnBehalfOf` | POST `/jobspecs/put-jobspecs-on-behalf-of` | catalog (sourcemap only) | not implemented |
| `putJobSpecs2` | POST `/jobspecs/put-jobspecs2` | catalog (sourcemap only) | not implemented |
| `removeJobSpecs` | POST `/jobspecs/remove-jobspecs` | catalog (sourcemap only) | not implemented |
| `removeJobSpecs2` | POST `/jobspecs/remove-jobspecs2` | catalog (sourcemap only) | not implemented |
| `getJobSpecInGraph` | GET `/jobspecs/{jobSpecRid}` | catalog (sourcemap only) | not implemented |
| `cancelJobsInBuild` | DELETE `/manager/builds/{buildRid}` | catalog (sourcemap only) | not implemented |
| `canCancelJobsInBuild` | GET `/manager/can-cancel-jobs-in-build/{buildRid}` | catalog (sourcemap only) | not implemented |
| `canCancelJobsInBuilds` | POST `/manager/can-cancel-jobs-in-builds` | catalog (sourcemap only) | not implemented |
| `canRerunBuild` | GET `/manager/can-rerun-build/{buildRid}` | catalog (sourcemap only) | not implemented |
| `canRerunBuilds` | POST `/manager/can-rerun-builds` | catalog (sourcemap only) | not implemented |
| `canRerunJobWithDebug` | GET `/manager/can-rerun-job-with-debug/{jobRid}` | catalog (sourcemap only) | not implemented |
| `getBuildPolicies` | POST `/manager/get-policies` | catalog (sourcemap only) | not implemented |
| `cancelJob` | DELETE `/manager/jobs/{jobRid}` | catalog (sourcemap only) | not implemented |
| `getBuildPolicy` | GET `/manager/policies/{datasetRid}` | catalog (sourcemap only) | not implemented |
| `putJobSpecAndBuild` | POST `/manager/put-jobspec-and-build` | catalog (sourcemap only) | not implemented |
| `removeBuildPolicies` | POST `/manager/remove-policies` | catalog (sourcemap only) | not implemented |
| `rerunBuild` | POST `/manager/rerun-build` | catalog (sourcemap only) | not implemented |
| `rerunJobWithDebug` | POST `/manager/rerun-job-with-debug` | catalog (sourcemap only) | not implemented |
| `resolveBuild2OnBehalf` | POST `/manager/resolve-build2-on-behalf` | catalog (sourcemap only) | not implemented |
| `resolveBuild` | POST `/manager/resolveBuild` | catalog (sourcemap only) | not implemented |
| `resolveBuild2` | POST `/manager/resolveBuild2` | catalog (sourcemap only) | not implemented |
| `runBuild` | POST `/manager/runBuild/branches/{branch}` | catalog (sourcemap only) | not implemented |
| `runDatasetBuild` | POST `/manager/runDatasetBuild/branches/{branch}` | catalog (sourcemap only) | not implemented |
| `setBuildPolicies` | POST `/manager/set-policies` | catalog (sourcemap only) | not implemented |
| `submitBuildOnBehalf` | POST `/manager/submit-build-on-behalf` | catalog (sourcemap only) | not implemented |
| `submitScheduledBuild` | POST `/manager/submit-scheduled-build` | catalog (sourcemap only) | not implemented |
| `submitBuild` | POST `/manager/submitBuild` | catalog (sourcemap only) | not implemented |

#### `monocle` (13 endpoints; base `/monocle/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getGraph` | POST `/links` | VERIFIED | not implemented |
| `getDownstreamObjects` | POST `/links/downstreamObjects` | VERIFIED | not implemented |
| `getDownstreamObjectsV2` | POST `/links/downstreamObjectsV2` | VERIFIED | not implemented |
| `getDownstreamObjectsV3` | POST `/links/downstreamObjectsV3` | VERIFIED | not implemented (least-exercised) |
| `getGraphV2` | POST `/links/graphV2` | VERIFIED | not implemented |
| `getGraphV3` | POST `/links/graphV3` | VERIFIED | internal-only via `pltr dependency` (ACP-06) |
| `getHierarchy` | POST `/links/hierarchy` | VERIFIED | not implemented |
| `getHierarchyV2` | POST `/links/hierarchyV2` | VERIFIED | not implemented |
| `getHierarchyV3` | POST `/links/hierarchyV3` | VERIFIED | not implemented |
| `getIntersection` | POST `/links/intersection` | VERIFIED | not implemented |
| `getIntersectionV2` | POST `/links/intersectionV2` | VERIFIED | not implemented |
| `getIntersectionV3` | POST `/links/intersectionV3` | VERIFIED | not implemented |
| `sourceInfo` | POST `/links/source` | VERIFIED | not implemented |

#### `stemma` (43 endpoints; base `/stemma/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getRepositories` | GET `/repos` | catalog (sourcemap only) | not implemented |
| `createRepository` | POST `/repos` | catalog (sourcemap only) | not implemented |
| `getRepositoriesBatched` | GET `/repos-batched` | catalog (sourcemap only) | not implemented |
| `getBatchHeadCommits` | POST `/repos/batch/headCommit` | catalog (sourcemap only) | not implemented |
| `getBatchCommitCheckResults` | POST `/repos/checks/batch` | catalog (sourcemap only) | not implemented |
| `getLatestUserForCommitHash` | POST `/repos/commits/commit-hash-user-info` | catalog (sourcemap only) | not implemented |
| `gitLog` | GET `/repos/commits/{gitRevRange}` | catalog (sourcemap only) | not implemented |
| `getToggleableWebhooks` | GET `/repos/toggleableWebhooks` | catalog (sourcemap only) | not implemented |
| `gitFileChangesv2` | GET `/repos/v2/diff/{gitRevPair}` | catalog (sourcemap only) | not implemented |
| `deleteRepository` | DELETE `/repos/{repositoryRid}` | catalog (sourcemap only) | not implemented |
| `getRepository` | GET `/repos/{repositoryRid}` | catalog (sourcemap only) | not implemented |
| `createRepositoryWithRid` | POST `/repos/{repositoryRid}` | catalog (sourcemap only) | not implemented |
| `getRequiredChecksForBranches` | POST `/repos/{repositoryRid}/batch/checks/required` | catalog (sourcemap only) | not implemented |
| `removeRequiredChecks` | DELETE `/repos/{repositoryRid}/branches/{branchName}/checks/required` | catalog (sourcemap only) | not implemented |
| `getRequiredChecksByBranch` | GET `/repos/{repositoryRid}/branches/{branchName}/checks/required` | catalog (sourcemap only) | not implemented |
| `addRequiredChecks` | PUT `/repos/{repositoryRid}/branches/{branchName}/checks/required` | catalog (sourcemap only) | not implemented |
| `getCommitChecksForAllRefs` | GET `/repos/{repositoryRid}/checks` | catalog (sourcemap only) | not implemented |
| `getKnownCommitCheckNames` | GET `/repos/{repositoryRid}/checks/known` | catalog (sourcemap only) | not implemented |
| `getRequiredChecks` | GET `/repos/{repositoryRid}/checks/required` | catalog (sourcemap only) | not implemented |
| `createCommitCheckResult` | POST `/repos/{repositoryRid}/commits/{commitHash}/checks` | catalog (sourcemap only) | not implemented |
| `getCommitCheckResults` | GET `/repos/{repositoryRid}/commits/{commitish}/checks` | catalog (sourcemap only) | not implemented |
| `getForks` | GET `/repos/{repositoryRid}/forks` | catalog (sourcemap only) | not implemented |
| `changeDefaultBranch` | PUT `/repos/{repositoryRid}/head` | catalog (sourcemap only) | not implemented |
| `createRef` | POST `/repos/{repositoryRid}/refs` | catalog (sourcemap only) | not implemented |
| `deleteRef` | DELETE `/repos/{repositoryRid}/refs/{ref}` | catalog (sourcemap only) | not implemented |
| `getToggleableWebhooksForRepository` | GET `/repos/{repositoryRid}/toggleableWebhooks` | catalog (sourcemap only) | not implemented |
| `toggleWebhook` | PUT `/repos/{repositoryRid}/toggleableWebhooks/{toggleableWebhookName}/toggle` | catalog (sourcemap only) | not implemented |
| `resolveCommitishes` | POST `/repos/{rid}/batch/resolve` | catalog (sourcemap only) | not implemented |
| `gitBlame` | GET `/repos/{rid}/blame/{path}` | catalog (sourcemap only) | not implemented |
| `branchStatus` | GET `/repos/{rid}/branchStatus` | catalog (sourcemap only) | not implemented |
| `gitBranches` | GET `/repos/{rid}/branches` | catalog (sourcemap only) | not implemented |
| `gitHead` | GET `/repos/{rid}/head` | catalog (sourcemap only) | not implemented |
| `getBulkPathContents` | GET `/repos/{rid}/paths/bulk-contents/{path}` | catalog (sourcemap only) | not implemented |
| `getPathContents` | GET `/repos/{rid}/paths/contents/{path}` | catalog (sourcemap only) | not implemented |
| `getPathMetadata` | GET `/repos/{rid}/paths/metadata/{path}` | catalog (sourcemap only) | not implemented |
| `searchPaths` | GET `/repos/{rid}/paths/search` | catalog (sourcemap only) | not implemented |
| `getPathTree` | GET `/repos/{rid}/paths/tree/{path}` | catalog (sourcemap only) | not implemented |
| `resolveCommits` | POST `/repos/{rid}/resolve-commits` | catalog (sourcemap only) | not implemented |
| `resolveCommitish` | GET `/repos/{rid}/resolve/{commitish}` | catalog (sourcemap only) | not implemented |
| `gitTags` | GET `/repos/{rid}/tags` | catalog (sourcemap only) | not implemented |
| `gitBranchesV2` | GET `/repos/{rid}/v2/branches` | catalog (sourcemap only) | not implemented |
| `gitTagsV2` | GET `/repos/{rid}/v2/tags` | catalog (sourcemap only) | not implemented |
| `createFork` | POST `/repos/{sourceRepositoryRid}/forks` | catalog (sourcemap only) | not implemented |

#### `stemma-pull-request` (29 endpoints; base `/stemma-pull-request/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getPullRequests` | GET `/pulls` | catalog (sourcemap only) | not implemented |
| `createPullRequest` | POST `/pulls` | catalog (sourcemap only) | not implemented |
| `getOrCreatePullRequest` | PUT `/pulls` | catalog (sourcemap only) | not implemented |
| `getBatchLatestPullRequests` | POST `/pulls/batch` | catalog (sourcemap only) | not implemented |
| `getPullRequestForBranches` | POST `/pulls/branch/pull-requests/batch` | catalog (sourcemap only) | not implemented |
| `updateFileComment` | PUT `/pulls/comments/file/{commentRid}` | catalog (sourcemap only) | not implemented |
| `updateGlobalComment` | PUT `/pulls/comments/global/{commentRid}` | catalog (sourcemap only) | not implemented |
| `deleteComment` | DELETE `/pulls/comments/{commentRid}` | catalog (sourcemap only) | not implemented |
| `batchReviewPullRequests` | PUT `/pulls/review/batch` | catalog (sourcemap only) | not implemented |
| `batchUpdatePullRequests` | PUT `/pulls/update/batch` | catalog (sourcemap only) | not implemented |
| `getPullRequestsV2` | POST `/pulls/v2` | catalog (sourcemap only) | not implemented |
| `batchMergePullRequests` | POST `/pulls/v2/merge/batch` | catalog (sourcemap only) | not implemented |
| `mergePullRequest` | POST `/pulls/v2/{pullRequestRid}/merge` | catalog (sourcemap only) | not implemented |
| `getPullRequest` | GET `/pulls/{pullRequestRid}` | catalog (sourcemap only) | not implemented |
| `getApprovalResult` | GET `/pulls/{pullRequestRid}/approval` | catalog (sourcemap only) | not implemented |
| `getFileComments` | GET `/pulls/{pullRequestRid}/comments/file` | catalog (sourcemap only) | not implemented |
| `createFileComment` | POST `/pulls/{pullRequestRid}/comments/file` | catalog (sourcemap only) | not implemented |
| `getTransformedFileComments` | GET `/pulls/{pullRequestRid}/comments/file/transformed` | catalog (sourcemap only) | not implemented |
| `getGlobalComments` | GET `/pulls/{pullRequestRid}/comments/global` | catalog (sourcemap only) | not implemented |
| `createGlobalComment` | POST `/pulls/{pullRequestRid}/comments/global` | catalog (sourcemap only) | not implemented |
| `getTransformedCommentLocations` | POST `/pulls/{pullRequestRid}/comments/transformedLocations` | catalog (sourcemap only) | not implemented |
| `mergePullRequestDeprecated` | POST `/pulls/{pullRequestRid}/merge` | catalog (sourcemap only) | not implemented |
| `getMergeInfo` | GET `/pulls/{pullRequestRid}/merge/info` | catalog (sourcemap only) | not implemented |
| `getPullRequestRecord` | GET `/pulls/{pullRequestRid}/record` | catalog (sourcemap only) | not implemented |
| `getPullRequestRecords` | GET `/pulls/{pullRequestRid}/record/all` | catalog (sourcemap only) | not implemented |
| `retriggerChecks` | POST `/pulls/{pullRequestRid}/retrigger-checks` | catalog (sourcemap only) | not implemented |
| `reviewPullRequest` | PUT `/pulls/{pullRequestRid}/review` | catalog (sourcemap only) | not implemented |
| `updatePullRequest` | PUT `/pulls/{pullRequestRid}/update` | catalog (sourcemap only) | not implemented |
| `getV2ApprovalResult` | GET `/pulls/{pullRequestRid}/v2-approval` | catalog (sourcemap only) | not implemented |

#### `foundry-catalog` (51 endpoints; base `/foundry-catalog/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `deleteBatchBranches` | DELETE `/catalog/batch/branches` | catalog (sourcemap only) | not implemented |
| `createBatchBranches2` | POST `/catalog/batch/branches/branchesCreate2` | catalog (sourcemap only) | not implemented |
| `getBatchDatasets2` | POST `/catalog/batch/datasets2` | catalog (sourcemap only) | not implemented |
| `createDataset2` | POST `/catalog/createDataset2` | catalog (sourcemap only) | not implemented |
| `createDatasetWithParent` | POST `/catalog/createDatasetWithParent` | catalog (sourcemap only) | not implemented |
| `deleteDataset` | DELETE `/catalog/datasets` | catalog (sourcemap only) | not implemented |
| `getDatasets` | GET `/catalog/datasets` | catalog (sourcemap only) | not implemented |
| `createDataset` | POST `/catalog/datasets` | catalog (sourcemap only) | not implemented |
| `getAllDatasetsAndBranches` | POST `/catalog/datasets/branches` | catalog (sourcemap only) | not implemented |
| `updateBatchBranches2` | POST `/catalog/datasets/branchesUpdate2` | catalog (sourcemap only) | not implemented |
| `getDataset` | GET `/catalog/datasets/{datasetRid}` | catalog (sourcemap only) | not implemented |
| `getBranches` | GET `/catalog/datasets/{datasetRid}/branches` | catalog (sourcemap only) | not implemented |
| `deleteBranch` | DELETE `/catalog/datasets/{datasetRid}/branches/{branchId}` | catalog (sourcemap only) | not implemented |
| `getBranch2` | GET `/catalog/datasets/{datasetRid}/branches2/{branchId}` | catalog (sourcemap only) | not implemented |
| `createBranch2` | POST `/catalog/datasets/{datasetRid}/branchesUnrestricted2/{branchId}` | catalog (sourcemap only) | not implemented |
| `updateBranch2` | POST `/catalog/datasets/{datasetRid}/branchesUpdate2/{branchId}` | catalog (sourcemap only) | not implemented |
| `getReverseTransactionsInView` | GET `/catalog/datasets/{datasetRid}/reverse-transactions-in-view/{viewTransactionRid}/from/{newestTransactionRid}` | catalog (sourcemap only) | not implemented |
| `getReverseTransactions2` | GET `/catalog/datasets/{datasetRid}/reverse-transactions2/{startRef}` | catalog (sourcemap only) | not implemented |
| `startTransaction` | POST `/catalog/datasets/{datasetRid}/transactions` | catalog (sourcemap only) | not implemented |
| `getTransaction` | GET `/catalog/datasets/{datasetRid}/transactions/{ref}` | catalog (sourcemap only) | not implemented |
| `setTransactionType` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}` | catalog (sourcemap only) | not implemented |
| `abortTransaction` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/abortWithMetadata` | catalog (sourcemap only) | not implemented |
| `commitTransaction` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/commit` | catalog (sourcemap only) | not implemented |
| `completeDeletion` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/completeDeletion` | catalog (sourcemap only) | not implemented |
| `addFilesToDeleteTransaction` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/addToDeleteTransaction` | catalog (sourcemap only) | not implemented |
| `closeFile` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/close/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `openFile` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/open/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `openFileTempCreds` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/openTempCreds/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `getFilesInTransactionPaged2` | GET `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/paged2` | catalog (sourcemap only) | not implemented |
| `getFilesInTransactionPagedTempCreds` | GET `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/pagedTempCreds` | catalog (sourcemap only) | not implemented |
| `pathReplace2` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/pathReplace2` | catalog (sourcemap only) | not implemented |
| `registerFiles` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/register` | catalog (sourcemap only) | not implemented |
| `removeFile` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/remove` | catalog (sourcemap only) | not implemented |
| `renameFiles2` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/files/rename2` | catalog (sourcemap only) | not implemented |
| `setTransactionProvenance` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/provenance` | catalog (sourcemap only) | not implemented |
| `unmarkDeletedTransaction` | POST `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/unmark` | catalog (sourcemap only) | not implemented |
| `deleteTransactionDataVoid` | DELETE `/catalog/datasets/{datasetRid}/transactions/{transactionRid}/void` | catalog (sourcemap only) | not implemented |
| `getDatasetViewFile2` | GET `/catalog/datasets/{datasetRid}/views/{endRef}/file2/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `getBatchDatasetViewFile2TempCreds` | POST `/catalog/datasets/{datasetRid}/views/{endRef}/fileTempCreds/batch` | catalog (sourcemap only) | not implemented |
| `getDatasetViewFile2TempCreds` | GET `/catalog/datasets/{datasetRid}/views/{endRef}/fileTempCreds/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `getDatasetViewStats` | GET `/catalog/datasets/{datasetRid}/views/{endRef}/stats` | catalog (sourcemap only) | not implemented |
| `getDatasetViewDifference` | GET `/catalog/datasets/{datasetRid}/views/{endTransactionRid}/diff/{previousEndTransactionRid}` | catalog (sourcemap only) | not implemented |
| `getReadFilesPermissionForDatasetView` | GET `/catalog/datasets/{datasetRid}/views/{endTransactionRid}/read-files-permission` | catalog (sourcemap only) | not implemented |
| `getDatasetViewFileTemporaryCredentials2` | POST `/catalog/datasets/{datasetRid}/views2/{endRef}/credentials/{logicalPath}` | catalog (sourcemap only) | not implemented |
| `getDatasetViewFiles2` | GET `/catalog/datasets/{datasetRid}/views2/{endRef}/files` | catalog (sourcemap only) | not implemented |
| `getDatasetViewFiles2TempCreds` | GET `/catalog/datasets/{datasetRid}/views2/{endRef}/filesTempCreds` | catalog (sourcemap only) | not implemented |
| `getDatasetViewRange2` | GET `/catalog/datasets/{datasetRid}/views2/{endRef}/range` | catalog (sourcemap only) | not implemented |
| `getEvents` | GET `/catalog/events` | catalog (sourcemap only) | not implemented |
| `getLatestEventOffset` | GET `/catalog/events/offset` | catalog (sourcemap only) | not implemented |
| `getFileSystems` | GET `/catalog/fileSystems` | catalog (sourcemap only) | not implemented |
| `updateDatasetBackingFilesystem` | POST `/catalog/updateDatasetBackingFileSystem` | catalog (sourcemap only) | not implemented |

#### `foundry-datahealth` (46 endpoints; base `/foundry-datahealth/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `createCheckGroup` | POST `/checkgroups` | catalog (sourcemap only) | not implemented |
| `getAllCheckGroups` | GET `/checkgroups/all` | VERIFIED | not implemented |
| `bulkGetCheckGroups` | POST `/checkgroups/bulk/get` | catalog (sourcemap only) | not implemented |
| `getCheckGroupsPermission` | POST `/checkgroups/permission` | catalog (sourcemap only) | not implemented |
| `deleteCheckGroup` | DELETE `/checkgroups/{checkGroupRid}` | catalog (sourcemap only) | not implemented |
| `getCheckGroup` | GET `/checkgroups/{checkGroupRid}` | catalog (sourcemap only) | not implemented |
| `updateCheckGroup` | POST `/checkgroups/{checkGroupRid}` | catalog (sourcemap only) | not implemented |
| `addChecksToCheckGroup` | POST `/checkgroups/{checkGroupRid}/add` | catalog (sourcemap only) | not implemented |
| `getAllChecksInGroup` | GET `/checkgroups/{checkGroupRid}/checks` | catalog (sourcemap only) | not implemented |
| `setPermissionCheckGroup` | POST `/checkgroups/{checkGroupRid}/permission/set` | catalog (sourcemap only) | not implemented |
| `getUsersPermission` | GET `/checkgroups/{checkGroupRid}/permission/users` | catalog (sourcemap only) | not implemented |
| `removeChecksFromCheckGroup` | POST `/checkgroups/{checkGroupRid}/remove` | catalog (sourcemap only) | not implemented |
| `getCheckReportsForEvents` | POST `/checks/reports/v2/events` | catalog (sourcemap only) | not implemented |
| `getLatestCheckReports` | POST `/checks/reports/v2/latest` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `getCheckReport` | GET `/checks/reports/v2/{checkReportRid}` | catalog (sourcemap only) | not implemented |
| `getIncidents` | POST `/checks/state/batch/incidents` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `areChecksPaused` | POST `/checks/state/pause` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `isGlobalPauseFlagSet` | GET `/checks/state/pause/all` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `pauseAll` | POST `/checks/state/pause/all` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `pauseCheck` | POST `/checks/state/pause/{checkRid}` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `snoozeChecks` | POST `/checks/state/snooze` | catalog (sourcemap only) | not implemented |
| `getSnoozeDetails` | POST `/checks/state/snooze-details` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `getSnoozeHistory` | POST `/checks/state/snooze-history` | partial (shape/mount only) (shape confirmed; no real checks on stack) | not implemented |
| `unpauseAll` | POST `/checks/state/unpause/all` | catalog (sourcemap only) | not implemented |
| `unpauseCheck` | POST `/checks/state/unpause/{checkRid}` | catalog (sourcemap only) | not implemented |
| `unsnoozeChecks` | POST `/checks/state/unsnooze` | catalog (sourcemap only) | not implemented |
| `createCheck` | POST `/checks/v2` | catalog (sourcemap only) | not implemented |
| `getAvailableCheckInfos` | GET `/checks/v2/available` | VERIFIED | not implemented |
| `filterByManageCheckPermission` | PUT `/checks/v2/batch/filterByManageCheck` | catalog (sourcemap only) | not implemented |
| `deleteChecks` | DELETE `/checks/v2/bulk` | catalog (sourcemap only) | not implemented |
| `bulkCreateCheck` | POST `/checks/v2/bulk` | catalog (sourcemap only) | not implemented |
| `bulkGetChecks` | POST `/checks/v2/bulk/get` | catalog (sourcemap only) | not implemented |
| `getChecksByAgent` | GET `/checks/v2/by-agent/{agentRid}` | catalog (sourcemap only) | not implemented |
| `bulkGetCheckRidsByDatasets` | POST `/checks/v2/by-dataset/bulk` | partial (shape/mount only) (field name UNVERIFIED; 400) | not implemented |
| `bulkGetCheckRidsBySchedules` | POST `/checks/v2/by-schedule/bulk` | catalog (sourcemap only) | not implemented |
| `getChecksBySchedule` | GET `/checks/v2/by-schedule/{scheduleRid}` | VERIFIED | not implemented |
| `getChecksByTable` | GET `/checks/v2/by-table/{tableRid}` | VERIFIED | not implemented |
| `hasManageAllChecksPermission` | GET `/checks/v2/hasManageAllChecksPermission` | VERIFIED | not implemented |
| `reindexCheckExperimental` | POST `/checks/v2/reindex/{checkRid}` | catalog (sourcemap only) | not implemented |
| `deleteCheck` | DELETE `/checks/v2/{checkRid}` | catalog (sourcemap only) | not implemented |
| `getCheck` | GET `/checks/v2/{checkRid}` | catalog (sourcemap only) | not implemented |
| `updateCheck` | POST `/checks/v2/{checkRid}` | catalog (sourcemap only) | not implemented |
| `hasManageCheckPermission` | GET `/checks/v2/{datasetRid}/hasManageCheckPermission` | catalog (sourcemap only) | not implemented |
| `getChecks` | GET `/checks/v2/{datasetRid}/{branchId}` | VERIFIED | not implemented |
| `addChecksToMonitoringView` | POST `/monitoring/checks/{monitoringViewRid}/add` | catalog (sourcemap only) | not implemented |
| `removeChecksFromMonitoringView` | POST `/monitoring/checks/{monitoringViewRid}/remove` | catalog (sourcemap only) | not implemented |

#### `foundry-metadata` (28 endpoints; base `/foundry-metadata/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getBatchNamespacedDatasetViewMetadatas` | POST `/metadata/batch/namespaced-dataset-view-metadatas` | catalog (sourcemap only) | not implemented |
| `getDatasetMetadataDeprecated` | GET `/metadata/datasets/{datasetRid}` | catalog (sourcemap only) | not implemented |
| `putDatasetMetadataDeprecated` | POST `/metadata/datasets/{datasetRid}` | catalog (sourcemap only) | not implemented |
| `getDatasetMetadatasDeprecated` | GET `/metadata/datasets/{datasetRid}/all` | catalog (sourcemap only) | not implemented |
| `getDatasetViewMetadata` | GET `/metadata/datasets/{datasetRid}/branches/{branchId}/view` | catalog (sourcemap only) | not implemented |
| `getDatasetViewMetadatas` | GET `/metadata/datasets/{datasetRid}/branches/{branchId}/view/all` | catalog (sourcemap only) | not implemented |
| `getNamespacedDatasetViewMetadata` | GET `/metadata/datasets/{datasetRid}/branches/{branchId}/view/namespace/{namespace}` | catalog (sourcemap only) | not implemented |
| `putDatasetViewMetadata` | POST `/metadata/datasets/{datasetRid}/branches/{branchId}/view/namespace/{namespace}` | catalog (sourcemap only) | not implemented |
| `deleteDatasetViewMetadata` | DELETE `/metadata/datasets/{datasetRid}/branches/{branchId}/view/version/{versionId}` | catalog (sourcemap only) | not implemented |
| `getLatestDatasetViewMetadataId` | GET `/metadata/datasets/{datasetRid}/branches/{branchId}/view/{endTransactionRid}/latestid` | catalog (sourcemap only) | not implemented |
| `getTransactionMetadataDeprecated` | GET `/metadata/datasets/{datasetRid}/transactions/{transactionRid}` | catalog (sourcemap only) | not implemented |
| `putTransactionMetadataDeprecated` | POST `/metadata/datasets/{datasetRid}/transactions/{transactionRid}` | catalog (sourcemap only) | not implemented |
| `getTransactionMetadatasDeprecated` | GET `/metadata/datasets/{datasetRid}/transactions/{transactionRid}/all` | catalog (sourcemap only) | not implemented |
| `deleteNamespacedTransactionMetadata` | DELETE `/metadata/datasets/{datasetRid}/transactions/{transactionRid}/namespaces` | catalog (sourcemap only) | not implemented |
| `deleteNamespacedTransactionMetadataPaged` | DELETE `/metadata/datasets/{datasetRid}/transactions/{transactionRid}/namespaces/paged` | catalog (sourcemap only) | not implemented |
| `deleteTransactionMetadata` | DELETE `/metadata/datasets/{datasetRid}/transactions/{transactionRid}/version/{versionId}` | catalog (sourcemap only) | not implemented |
| `deleteDatasetMetadata` | DELETE `/metadata/datasets/{datasetRid}/version/{versionId}` | catalog (sourcemap only) | not implemented |
| `getEvents` | GET `/metadata/events` | catalog (sourcemap only) | not implemented |
| `getLatestEventOffset` | GET `/metadata/events/offset` | catalog (sourcemap only) | not implemented |
| `getDatasetMetadata` | GET `/metadata/v2/datasets/{datasetRid}` | catalog (sourcemap only) | not implemented |
| `getDatasetMetadatas` | GET `/metadata/v2/datasets/{datasetRid}/all` | catalog (sourcemap only) | not implemented |
| `getNamespacedDatasetMetadata` | GET `/metadata/v2/datasets/{datasetRid}/namespace/{namespace}` | catalog (sourcemap only) | not implemented |
| `putDatasetMetadata` | POST `/metadata/v2/datasets/{datasetRid}/namespace/{namespace}` | catalog (sourcemap only) | not implemented |
| `getTransactionMetadataForAllNamespaces` | GET `/metadata/v2/datasets/{datasetRid}/transactions/{transactionRid}` | catalog (sourcemap only) | not implemented |
| `deleteTransactionMetadatas` | DELETE `/metadata/v2/datasets/{datasetRid}/transactions/{transactionRid}/all` | catalog (sourcemap only) | not implemented |
| `getTransactionMetadatas` | GET `/metadata/v2/datasets/{datasetRid}/transactions/{transactionRid}/all` | catalog (sourcemap only) | not implemented |
| `getTransactionMetadata` | GET `/metadata/v2/datasets/{datasetRid}/transactions/{transactionRid}/namespace/{namespace}` | catalog (sourcemap only) | not implemented |
| `putTransactionMetadata` | POST `/metadata/v2/datasets/{datasetRid}/transactions/{transactionRid}/namespace/{namespace}` | catalog (sourcemap only) | not implemented |

#### `function-registry` (38 endpoints; base `/function-registry/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `createFunction` | POST `/functions` | catalog (sourcemap only) | not implemented |
| `batchValidateApiNames` | POST `/functions/batch/apiName/validate` | catalog (sourcemap only) | not implemented |
| `batchAppendOntologyBinding` | POST `/functions/batch/appendOntologyBinding` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionsForArtifacts` | POST `/functions/batch/artifacts/functions` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionsByIdentifiers` | POST `/functions/batch/identifiers` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionMetadatas` | POST `/functions/batch/metadata` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionsByParentCompassRid` | POST `/functions/batch/parent` | catalog (sourcemap only) | not implemented |
| `batchResolveSemanticVersionRange` | PUT `/functions/batch/resolve` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionSpecs` | POST `/functions/batch/specs` | catalog (sourcemap only) | not implemented |
| `batchRegisterFunctionSpecs` | POST `/functions/batch/specs/register` | catalog (sourcemap only) | not implemented |
| `batchGetFunctionSpecsV2` | POST `/functions/batch/specsV2` | catalog (sourcemap only) | not implemented |
| `batchUpdateUsageHistory` | PUT `/functions/batch/usageHistory` | catalog (sourcemap only) | not implemented |
| `getGlobalFunctionSpec` | GET `/functions/global/specs/{apiName}` | catalog (sourcemap only) | not implemented |
| `getFunctionByIdentifier` | POST `/functions/identifiers` | catalog (sourcemap only) | not implemented |
| `listFunctionSpecs` | POST `/functions/listFunctions` | catalog (sourcemap only) | not implemented |
| `getOntologyFunctionSpecs` | POST `/functions/ontology/{ontologyRid}/specs` | VERIFIED | not implemented |
| `batchGetOntologyFunctionSpecs` | POST `/functions/ontology/{ontologyRid}/specs/batch` | VERIFIED | not implemented |
| `getOntologyFunctionSpec` | GET `/functions/ontology/{ontologyRid}/specs/{apiName}` | VERIFIED | not implemented |
| `reindexFunctions` | POST `/functions/reindex` | catalog (sourcemap only) | not implemented |
| `searchFunctions` | POST `/functions/search` | catalog (sourcemap only) | not implemented |
| `deleteFunction` | DELETE `/functions/{functionRid}` | catalog (sourcemap only) | not implemented |
| `getFunctionMetadata` | GET `/functions/{functionRid}/metadata` | catalog (sourcemap only) | not implemented |
| `setFunctionDescription` | POST `/functions/{functionRid}/metadata/description` | catalog (sourcemap only) | not implemented |
| `setFunctionDisplayName` | POST `/functions/{functionRid}/metadata/display-name` | catalog (sourcemap only) | not implemented |
| `setFunctionVisibility` | PUT `/functions/{functionRid}/metadata/visibility` | catalog (sourcemap only) | not implemented |
| `resolveSemanticVersionRange` | PUT `/functions/{functionRid}/resolve` | catalog (sourcemap only) | not implemented |
| `registerFunctionSpec` | POST `/functions/{functionRid}/specs` | catalog (sourcemap only) | not implemented |
| `getFunctionSpec` | GET `/functions/{functionRid}/specs/{version}` | catalog (sourcemap only) | not implemented |
| `getUsageHistory` | GET `/functions/{functionRid}/usageHistory` | VERIFIED | planned (dependency Phase B fn-consumers) |
| `updateUsageHistory` | PUT `/functions/{functionRid}/usageHistory` | VERIFIED | planned (dependency Phase B fn-consumers) |
| `getFunctionVersions` | POST `/functions/{functionRid}/versions` | catalog (sourcemap only) | not implemented |
| `resolveImports` | PUT `/functionsRepositories/resolveImports` | catalog (sourcemap only) | not implemented |
| `getOntologyReferences` | GET `/functionsRepositories/{repositoryRid}/ontologyReferences` | VERIFIED (deprecated; empty) | not implemented |
| `addOntologyReferences` | POST `/functionsRepositories/{repositoryRid}/ontologyReferences/add` | VERIFIED (deprecated; empty) | not implemented |
| `removeOntologyReferences` | POST `/functionsRepositories/{repositoryRid}/ontologyReferences/remove` | VERIFIED (deprecated; empty) | not implemented |
| `setRepositoryImportMetadata` | POST `/functionsRepositories/{repositoryRid}/repositoryImportMetadata` | catalog (sourcemap only) | not implemented |
| `getRepositoryImports` | GET `/functionsRepositories/{repositoryRid}/repositoryImports` | VERIFIED (envelope only) | not implemented |
| `setRepositoryImports` | POST `/functionsRepositories/{repositoryRid}/repositoryImports` | VERIFIED (envelope only) | not implemented |

#### `third-party-application-service` (48 endpoints; base `/third-party-application-service/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getApplicationForSdkRepository` | GET `/application-sdks/for-repository/{repositoryRid}` | VERIFIED | not implemented |
| `createSdkV2` | POST `/application-sdks/v2/{applicationRid}` | catalog (sourcemap only) | not implemented |
| `bulkGetEntitySdkVersionsV2` | PUT `/application-sdks/v2/{applicationRid}/entity-sdk-versions` | catalog (sourcemap only) | not implemented |
| `listSdks` | GET `/application-sdks/{applicationRid}` | VERIFIED | not implemented |
| `bulkGetEntitySdkVersions` | PUT `/application-sdks/{applicationRid}/entity-sdk-versions` | VERIFIED | planned (dependency U7) |
| `getLatestSdk` | GET `/application-sdks/{applicationRid}/latest` | VERIFIED | not implemented |
| `getSdkRepositoryRid` | GET `/application-sdks/{applicationRid}/repository` | VERIFIED | not implemented |
| `getSdk` | GET `/application-sdks/{applicationRid}/{sdkVersion}` | VERIFIED | not implemented |
| `getWebsitesForCodeRepository` | GET `/application-websites/for-code-repository/{codeRepositoryRid}` | catalog (sourcemap only) | not implemented |
| `getApplicationForWebsiteRepository` | GET `/application-websites/for-repository/{repositoryRid}` | catalog (sourcemap only) | not implemented |
| `getWebsite` | GET `/application-websites/v2/{applicationRid}` | catalog (sourcemap only) | not implemented |
| `getWebsiteRepository` | GET `/application-websites/{applicationRid}` | catalog (sourcemap only) | not implemented |
| `linkWebsiteCodeRepository` | PUT `/application-websites/{applicationRid}/link` | catalog (sourcemap only) | not implemented |
| `updateWebsiteRoles` | PUT `/application-websites/{applicationRid}/roles` | catalog (sourcemap only) | not implemented |
| `listApplications` | GET `/applications` | VERIFIED | not implemented |
| `bulkGetApplications` | PUT `/applications/bulk` | VERIFIED | not implemented |
| `getApplicationRuntimeConfig` | GET `/applications/runtime-config` | VERIFIED | not implemented |
| `createApplicationV3` | POST `/applications/v3` | VERIFIED | not implemented |
| `createApplicationV4` | POST `/applications/v4` | VERIFIED | not implemented |
| `updateApplicationV4` | PUT `/applications/v4/{applicationRid}` | VERIFIED | not implemented |
| `createApplicationV5` | POST `/applications/v5` | VERIFIED | not implemented |
| `deleteApplication` | DELETE `/applications/{applicationRid}` | VERIFIED | not implemented |
| `getApplication` | GET `/applications/{applicationRid}` | VERIFIED | not implemented |
| `updateApplicationClientConfig` | PUT `/applications/{applicationRid}/client-config` | VERIFIED | not implemented |
| `revertCompassMigrationForApplication` | POST `/applications/{applicationRid}/do-not-use/move-to-service-project` | VERIFIED | not implemented |
| `makeApplicationUnscoped` | POST `/applications/{applicationRid}/make-unscoped` | VERIFIED | not implemented |
| `updateApplicationMcpSettings` | PUT `/applications/{applicationRid}/mcp-settings` | VERIFIED | not implemented |
| `updateApplicationMetadata` | PUT `/applications/{applicationRid}/metadata` | VERIFIED | not implemented |
| `migrateOperations` | PUT `/applications/{applicationRid}/migrate` | VERIFIED | not implemented |
| `migrateApplicationToCompass` | POST `/applications/{applicationRid}/migrate-to-compass` | VERIFIED | not implemented |
| `updateApplicationOrganizations` | PUT `/applications/{applicationRid}/organizations` | VERIFIED | not implemented |
| `updateApplicationRoles` | PUT `/applications/{applicationRid}/roles` | VERIFIED | not implemented |
| `updateApplicationScopes` | PUT `/applications/{applicationRid}/scoping` | VERIFIED | not implemented |
| `listApplicationVersions` | GET `/applications/{applicationRid}/versions` | VERIFIED | not implemented |
| `getApplicationVersion` | GET `/applications/{applicationRid}/versions/{applicationVersion}` | VERIFIED | not implemented |
| `deleteSdkPackage` | DELETE `/sdks/packages/{sdkPackageRid}` | catalog (sourcemap only) | not implemented |
| `getSdkPackage` | GET `/sdks/packages/{sdkPackageRid}` | catalog (sourcemap only) | not implemented |
| `listSdkPackages` | GET `/sdks/{repositoryRid}` | catalog (sourcemap only) | not implemented |
| `listSdks` | GET `/sdks/{repositoryRid}/{packageName}` | catalog (sourcemap only) | not implemented |
| `getResourceBindings` | GET `/sdks/{repositoryRid}/{packageName}/bindings` | catalog (sourcemap only) | not implemented |
| `getLatestSdk` | GET `/sdks/{repositoryRid}/{packageName}/latest` | catalog (sourcemap only) | not implemented |
| `getLatestSdkV2` | POST `/sdks/{repositoryRid}/{packageName}/latest/v2` | catalog (sourcemap only) | not implemented |
| `getSdkPackageRid` | GET `/sdks/{repositoryRid}/{packageName}/rid` | catalog (sourcemap only) | not implemented |
| `getSdk` | GET `/sdks/{repositoryRid}/{packageName}/{sdkVersion}` | catalog (sourcemap only) | not implemented |
| `createSdk` | POST `/sdks/{repositoryRid}/{packageName}/{sdkVersion}` | catalog (sourcemap only) | not implemented |
| `createSdkV2` | POST `/sdks/{repositoryRid}/{packageName}/{sdkVersion}/v2` | catalog (sourcemap only) | not implemented |
| `getResourceBindingsV2` | GET `/sdks/{sdkPackageRid}/{sdkVersion}/bindingsV2` | catalog (sourcemap only) | not implemented |
| `getSdkDataScope` | GET `/sdks/{sdkPackageRid}/{sdkVersion}/dataScope` | catalog (sourcemap only) | not implemented |

#### `magritte-coordinator` (34 endpoints; base `/magritte-coordinator/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `bulkExtendAgentRuntime` | POST `/source-store/source/agent/extend` | catalog (sourcemap only) | not implemented |
| `compassMigrationStatus` | GET `/source-store/source/migration/status` | catalog (sourcemap only) | not implemented |
| `addSourceV2` | POST `/source-store/source/v2` | catalog (sourcemap only) | not implemented |
| `addSourceV3` | POST `/source-store/source/v3` | catalog (sourcemap only) | not implemented |
| `deleteSource` | DELETE `/source-store/source/{sourceId}` | catalog (sourcemap only) | not implemented |
| `updateSource` | PUT `/source-store/source/{sourceId}` | catalog (sourcemap only) | not implemented |
| `getRecommendedAgentForSource` | GET `/source-store/source/{sourceId}/agent` | catalog (sourcemap only) | not implemented |
| `deleteAgentAssignment` | DELETE `/source-store/source/{sourceId}/agent/{agentId}` | catalog (sourcemap only) | not implemented |
| `getAssignedAgents` | GET `/source-store/source/{sourceId}/agents` | VERIFIED | not implemented |
| `getAssignedPcloudAgents` | GET `/source-store/source/{sourceId}/agents/pcloud` | VERIFIED | not implemented |
| `updateSourceApiName` | PUT `/source-store/source/{sourceId}/api-name` | catalog (sourcemap only) | not implemented |
| `getSourceConfig` | GET `/source-store/source/{sourceId}/config` | VERIFIED | not implemented |
| `updateSourceConfig` | PUT `/source-store/source/{sourceId}/config` | VERIFIED | not implemented |
| `getSourceConfigWithEncryptedValues` | GET `/source-store/source/{sourceId}/config/{agentId}` | VERIFIED | not implemented |
| `getSourceDescription` | GET `/source-store/source/{sourceId}/description` | VERIFIED | not implemented |
| `updateSourceDescription` | PUT `/source-store/source/{sourceId}/description` | VERIFIED | not implemented |
| `updateSourceDisplayOptions` | PUT `/source-store/source/{sourceId}/display-options` | catalog (sourcemap only) | not implemented |
| `migrateToCompass` | PUT `/source-store/source/{sourceId}/migrate` | catalog (sourcemap only) | not implemented |
| `setRuntimePlatform` | PUT `/source-store/source/{sourceId}/runtimePlatform` | catalog (sourcemap only) | not implemented |
| `updateRuntimePlatform` | POST `/source-store/source/{sourceId}/runtimePlatform/update` | catalog (sourcemap only) | not implemented |
| `getRuntimePlatform` | GET `/source-store/source/{sourceId}/runtimePlatform/v2` | VERIFIED | not implemented |
| `getSourceConfigWithPlaintextSecretValues` | POST `/source-store/source/{sourceId}/v2/getSourceConfigWithPlaintextSecretValues` | catalog (sourcemap only) | not implemented |
| `getSourceConfigs` | GET `/source-store/sources` | catalog (sourcemap only) | not implemented |
| `getSourcesForAgents` | POST `/source-store/sources/agents` | catalog (sourcemap only) | not implemented |
| `bulkGetAssignedAgents` | POST `/source-store/sources/agents/bulk` | catalog (sourcemap only) | not implemented |
| `bulkGetAssignedPcloudAgents` | POST `/source-store/sources/agents/pcloud/bulk` | catalog (sourcemap only) | not implemented |
| `bulkGetSourceApiNames` | POST `/source-store/sources/api-names/bulk` | catalog (sourcemap only) | not implemented |
| `bulkGetSourceConfig` | POST `/source-store/sources/config/bulk` | catalog (sourcemap only) | not implemented |
| `bulkGetSourceDescription` | POST `/source-store/sources/description/bulk` | catalog (sourcemap only) | not implemented |
| `getSourceDescriptions` | GET `/source-store/sources/descriptions` | VERIFIED | not implemented |
| `getSourcesThatImportEgressPolicies` | POST `/source-store/sources/egress-policies` | partial (shape/mount only) (422; shape off) | not implemented |
| `getMetadata` | POST `/source-store/sources/metadata` | partial (shape/mount only) (422; shape off) | not implemented |
| `getAllSourceIds` | GET `/source-store/sources/rids` | VERIFIED | not implemented |
| `getSourcesByType` | GET `/source-store/sources/types` | VERIFIED | not implemented |

#### `branch-service` (23 endpoints; base `/branch-service/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `abortDeployment` | PUT `/branch/abort-deployment` | catalog (sourcemap only) | not implemented |
| `addResourcesToBranch` | PUT `/branch/add-resources` | catalog (sourcemap only) | not implemented |
| `getBackendInformation` | GET `/branch/backend-information` | VERIFIED | not implemented |
| `getResourcesOnBranch` | PUT `/branch/branch-resources/{branchRid}` | catalog (sourcemap only) | not implemented |
| `getResourceVersionsOnBranch` | PUT `/branch/branch-versions/{branchRid}` | catalog (sourcemap only) | not implemented |
| `checkProposalDeployable` | PUT `/branch/check-deployable/branch/{branchRid}/proposal/{proposalRid}` | catalog (sourcemap only) | not implemented |
| `checkBranchPreviewable` | PUT `/branch/check-previewable/branch/{branchRid}` | catalog (sourcemap only) | not implemented |
| `closeBranch` | PUT `/branch/close/{branchRid}` | catalog (sourcemap only) | not implemented |
| `createBranch` | POST `/branch/create` | catalog (sourcemap only) | not implemented |
| `getResourceDependencyGraph` | PUT `/branch/dependency-graph/{branchRid}` | contract-only (req verified; no live branch) | not implemented |
| `deployProposal` | POST `/branch/deploy-proposal/branch/{branchRid}/proposal/{proposalRid}` | catalog (sourcemap only) | not implemented |
| `getDeploymentHistory` | PUT `/branch/deployment-history` | catalog (sourcemap only) | not implemented |
| `getDeploymentRecord` | PUT `/branch/deployment-record` | catalog (sourcemap only) | not implemented |
| `getBranch` | PUT `/branch/load/{branchRid}` | catalog (sourcemap only) | not implemented |
| `markBranchAsActive` | PUT `/branch/mark-active/{branchRid}` | catalog (sourcemap only) | not implemented |
| `closeProposal` | PUT `/branch/proposal/close/{proposalRid}` | catalog (sourcemap only) | not implemented |
| `createProposal` | POST `/branch/proposal/create` | catalog (sourcemap only) | not implemented |
| `getProposal` | PUT `/branch/proposal/load/{proposalRid}` | catalog (sourcemap only) | not implemented |
| `updateProposal` | PUT `/branch/proposal/update/{proposalRid}` | catalog (sourcemap only) | not implemented |
| `updateBranch` | PUT `/branch/update/{branchRid}` | catalog (sourcemap only) | not implemented |
| `validateCanAddResourcesToBranch` | PUT `/branch/validate-add-resources-to-branch` | catalog (sourcemap only) | not implemented |
| `validateCanCreateBranchWithResources` | PUT `/branch/validate-create-branch-with-resources` | catalog (sourcemap only) | not implemented |
| `validateResourceAllowedOnBranch` | PUT `/branch/validate-resource` | catalog (sourcemap only) | not implemented |

#### `webhooks` (20 endpoints; base `/webhooks/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `createWebhook` | POST `/registry/v0` | catalog (sourcemap only) | not implemented |
| `bulkGetWebhooks` | POST `/registry/v0/bulk` | VERIFIED | not implemented |
| `bulkGetInternalWebhooks` | GET `/registry/v0/bulk/internal` | VERIFIED | not implemented |
| `getAllWebhookVersions` | GET `/registry/v0/bulk/{webhookRid}` | VERIFIED | not implemented |
| `bulkGetWebhooksByLocators` | POST `/registry/v0/locators` | catalog (sourcemap only) | not implemented |
| `getMagrittePluginsManifest` | GET `/registry/v0/plugins/magritte` | VERIFIED | not implemented |
| `resolveRequiredScopesForWebhookExecution` | POST `/registry/v0/resolveRequiredScopes` | catalog (sourcemap only) | not implemented |
| `bulkGetWebhooksLatestVersions` | PUT `/registry/v0/webhooks-getLatestVersion` | VERIFIED | not implemented |
| `bulkGetWebhookRidsForSources` | PUT `/registry/v0/webhooks-getRidsForSources` | VERIFIED | not implemented |
| `bulkGetFunctionRidsForWebhooks` | PUT `/registry/v0/webhooks/bulk/functionsRids` | catalog (sourcemap only) | not implemented |
| `createFunctionForWebhook` | PUT `/registry/v0/webhooks/{webhookRid}/functions` | catalog (sourcemap only) | not implemented |
| `publishFunctionVersionForLatestWebhookVersion` | PUT `/registry/v0/webhooks/{webhookRid}/functions/publish` | catalog (sourcemap only) | not implemented |
| `deleteWebhook` | DELETE `/registry/v0/{webhookRid}` | catalog (sourcemap only) | not implemented |
| `publishWebhookVersion` | POST `/registry/v0/{webhookRid}` | catalog (sourcemap only) | not implemented |
| `updateWebhookApiName` | POST `/registry/v0/{webhookRid}/api-name` | catalog (sourcemap only) | not implemented |
| `getWebhookLatestVersion` | GET `/registry/v0/{webhookRid}/latest` | VERIFIED | not implemented |
| `deprecatedUpdateWebhookMetadata` | POST `/registry/v0/{webhookRid}/metadata` | catalog (sourcemap only) | not implemented |
| `updateWebhookMetadata` | PUT `/registry/v0/{webhookRid}/metadata` | catalog (sourcemap only) | not implemented |
| `getWebhookVersion` | GET `/registry/v0/{webhookRid}/version/{version}` | VERIFIED | not implemented |
| `duplicateWebhook` | POST `/registry/v0/{webhookRid}/version/{webhookVersion}/duplicate` | catalog (sourcemap only) | not implemented |

#### `language-model-service` (15 endpoints; base `/language-model-service/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `createIndexAndResource` | PUT `/semantics/v1/createIndexAndResource/{indexLocator}/v2` | catalog (sourcemap only) | not implemented |
| `searchDocumentsMultiIndex` | POST `/semantics/v1/documents/search` | catalog (sourcemap only) | not implemented |
| `getIndices` | GET `/semantics/v1/indexes` | VERIFIED (empty) | not implemented |
| `createUserScopedIndex` | PUT `/semantics/v1/indexes` | VERIFIED (empty) | not implemented |
| `deleteIndex` | DELETE `/semantics/v1/indexes/{indexRid}` | VERIFIED (empty) | not implemented |
| `getIndex` | GET `/semantics/v1/indexes/{indexRid}` | VERIFIED (empty) | not implemented |
| `createIndex` | PUT `/semantics/v1/indexes/{indexRid}` | VERIFIED (empty) | not implemented |
| `getDocuments` | POST `/semantics/v1/indexes/{indexRid}/documents/get` | VERIFIED (empty) | not implemented |
| `getAllDocuments` | GET `/semantics/v1/indexes/{indexRid}/documents/get-all-ids` | VERIFIED (empty) | not implemented |
| `getDocumentsWithEmbeddings` | POST `/semantics/v1/indexes/{indexRid}/documents/getWithEmbeddings` | VERIFIED (empty) | not implemented |
| `searchDocuments` | POST `/semantics/v1/indexes/{indexRid}/documents/search` | VERIFIED (empty) | not implemented |
| `bulkSearchDocuments` | POST `/semantics/v1/indexes/{indexRid}/documents/search-bulk` | VERIFIED (empty) | not implemented |
| `updateDocuments` | POST `/semantics/v1/indexes/{indexRid}/documents/update` | VERIFIED (empty) | not implemented |
| `updateDocumentsWithEmbeddings` | POST `/semantics/v1/indexes/{indexRid}/documents/updateWithEmbeddings` | VERIFIED (empty) | not implemented |
| `createIndexV2` | PUT `/semantics/v1/indexes/{indexRid}/v2` | VERIFIED (empty) | not implemented |

#### `module-group` (34 endpoints; base `/module-group/api`)

> NOT MOUNTED on the verified stack (`Route:RouteNotMounted` on all probed prefixes).

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `createDeployedApp` | POST `/deployed-apps` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getDeployedApps` | PUT `/deployed-apps/bulk` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getRunningDeployedAppsPaginated` | POST `/deployed-apps/running-paginated` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `notifySourceChange` | PUT `/deployed-apps/source-change` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getComputeModuleStatus` | GET `/deployed-apps/{compassRid}/{branch}/status` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getComputeModuleDiagnostics` | GET `/deployed-apps/{compassRid}/{branch}/{moduleId}/diagnostics` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getDeployedApp` | GET `/deployed-apps/{deployedAppRid}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `updateDeployedApp` | PUT `/deployed-apps/{deployedAppRid}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getAllowedAuthModes` | GET `/deployed-apps/{deployedAppRid}/allowed-auth-modes` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getThirdPartyClientId` | GET `/deployed-apps/{deployedAppRid}/client-id` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getThirdPartyClientIdV2` | GET `/deployed-apps/{deployedAppRid}/client-id/v2` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getDeployedAppRunStatus` | GET `/deployed-apps/{deployedAppRid}/deployed-app-run-status` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `setApplicationPermissionCredentials` | POST `/deployed-apps/{deployedAppRid}/permissions` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getResourceProfiles` | GET `/deployed-apps/{deployedAppRid}/resource-profiles` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getDeployedAppV2` | GET `/deployed-apps/{deployedAppRid}/v2` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getCandidateBackendsOfComputeModule` | GET `/deployed-apps/{deployedAppRid}/{branch}/candidate-backends` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `configureDevMode` | PUT `/deployed-apps/{deployedAppRid}/{branch}/dev-mode` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getDeployedAppFunctionSchemas` | GET `/deployed-apps/{deployedAppRid}/{branch}/function-schemas` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getComputeModuleHistory` | POST `/deployed-apps/{deployedAppRid}/{branch}/history` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `executeOnComputeModule` | POST `/module-group-multiplexer/compute-modules/jobs/execute` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `submitToDeployedApp` | POST `/module-group-multiplexer/deployed-apps/jobs` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `executeOnDeployedApp` | POST `/module-group-multiplexer/deployed-apps/jobs/execute` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `cancelV2` | DELETE `/module-group-multiplexer/jobs` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `submit` | POST `/module-group-multiplexer/jobs` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobResultV2` | PUT `/module-group-multiplexer/jobs/result/v2` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobResultV3` | PUT `/module-group-multiplexer/jobs/result/v3` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobStatusV2` | PUT `/module-group-multiplexer/jobs/status/v2` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobStatusV3` | PUT `/module-group-multiplexer/jobs/status/v3` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `cancelV3` | DELETE `/module-group-multiplexer/jobs/v3` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `cancel` | DELETE `/module-group-multiplexer/jobs/{jobId}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobResult` | GET `/module-group-multiplexer/jobs/{jobId}/result` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `softCancel` | PUT `/module-group-multiplexer/jobs/{jobId}/soft-cancel` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getJobStatus` | GET `/module-group-multiplexer/jobs/{jobId}/status` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getComputeModuleSchemas` | GET `/module-group-multiplexer/schemas` | NOT MOUNTED (this stack) / catalog-only | not implemented |

#### `comments` (14 endpoints; base `/comments/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `batchGetCommentsDeprecated` | POST `/comments/batch` | catalog (sourcemap only) | not implemented |
| `batchGetCommentsPageDeprecated` | POST `/comments/batch/page` | catalog (sourcemap only) | not implemented |
| `batchGetCommentsPageV2` | POST `/comments/batch/page-v2` | catalog (sourcemap only) | not implemented |
| `bulkGetCommentCounts` | POST `/comments/counts` | VERIFIED | not implemented |
| `getCommentsPageDeprecated` | POST `/comments/page` | catalog (sourcemap only) | not implemented |
| `getCommentsPageV2` | POST `/comments/page-v2` | catalog (sourcemap only) | not implemented |
| `getCommentsDeprecated` | GET `/{resourceId}/comments` | catalog (sourcemap only) | not implemented |
| `addComment` | POST `/{resourceId}/comments` | catalog (sourcemap only) | not implemented |
| `bulkUpdateComments` | PUT `/{resourceId}/comments` | catalog (sourcemap only) | not implemented |
| `getCommentsById` | PUT `/{resourceId}/comments/by-id` | catalog (sourcemap only) | not implemented |
| `deleteComment` | DELETE `/{resourceId}/comments/{commentId}` | catalog (sourcemap only) | not implemented |
| `updateComment` | PUT `/{resourceId}/comments/{commentId}` | catalog (sourcemap only) | not implemented |
| `addReaction` | POST `/{resourceId}/comments/{commentId}/reactions` | catalog (sourcemap only) | not implemented |
| `deleteReaction` | DELETE `/{resourceId}/comments/{commentId}/reactions/{reaction}` | catalog (sourcemap only) | not implemented |

#### `resource-policy-manager` (26 endpoints; base `/resource-policy-manager/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `canAdministerNetworkControlsForResources` | POST `/network-egress-policies/can-administer-network` | catalog (sourcemap only) | not implemented |
| `canCreateNetworkPolicyApprovalRequests` | GET `/network-egress-policies/can-create-network-policy-approval-requests/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `checkPoliciesAccess` | POST `/network-egress-policies/check-access` | catalog (sourcemap only) | not implemented |
| `getNetworkPolicyConfigurationState` | GET `/network-egress-policies/configuration-state/{enrollment}` | catalog (sourcemap only) | not implemented |
| `createPolicy` | POST `/network-egress-policies/create` | catalog (sourcemap only) | not implemented |
| `createDisapprovedPolicyApprovalRequest` | POST `/network-egress-policies/create-disapproved-policy-approval-request` | catalog (sourcemap only) | not implemented |
| `createPendingApprovalPolicy` | POST `/network-egress-policies/create-pending-approval` | catalog (sourcemap only) | not implemented |
| `updateDescription` | POST `/network-egress-policies/description` | catalog (sourcemap only) | not implemented |
| `disapprovePolicy` | POST `/network-egress-policies/disapprove/{networkPolicyRid}` | catalog (sourcemap only) | not implemented |
| `getProjectEnrollmentPolicies` | POST `/network-egress-policies/enrollment/project/{projectRid}` | catalog (sourcemap only) | not implemented |
| `getEnrollmentPolicies` | POST `/network-egress-policies/enrollment/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `forceDeletePolicy` | DELETE `/network-egress-policies/force-delete/{policyRid}` | catalog (sourcemap only) | not implemented |
| `getAllPolicies` | POST `/network-egress-policies/get-all-policies` | catalog (sourcemap only) | not implemented |
| `getPolicies` | POST `/network-egress-policies/get-batch` | catalog (sourcemap only) | not implemented |
| `getOrCreateBucketPolicies` | POST `/network-egress-policies/get-or-create-bucket-policies` | catalog (sourcemap only) | not implemented |
| `getPoliciesForAgents` | POST `/network-egress-policies/get-policies-for-agents` | catalog (sourcemap only) | not implemented |
| `getPolicyApprovalRequests` | POST `/network-egress-policies/get-policy-approval-requests-batch` | catalog (sourcemap only) | not implemented |
| `getGlobalPoliciesForEnrollmentDeprecated` | GET `/network-egress-policies/global/enrollment/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `updateRevocation` | POST `/network-egress-policies/revocation` | catalog (sourcemap only) | not implemented |
| `updateTlsInspection` | POST `/network-egress-policies/tls-inspection` | catalog (sourcemap only) | not implemented |
| `updatePolicyPermissions` | POST `/network-egress-policies/update-permissions` | catalog (sourcemap only) | not implemented |
| `createPendingApprovalPolicyV2` | POST `/network-egress-policies/v2/create-pending-approval` | catalog (sourcemap only) | not implemented |
| `getProjectEnrollmentPoliciesV2` | POST `/network-egress-policies/v2/enrollment/project/{projectRid}` | catalog (sourcemap only) | not implemented |
| `getEnrollmentPoliciesV2` | POST `/network-egress-policies/v2/enrollment/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `getPoliciesV2` | POST `/network-egress-policies/v2/get-batch` | catalog (sourcemap only) | not implemented |
| `getFullPoliciesV2` | POST `/network-egress-policies/v2/get-full-batch` | catalog (sourcemap only) | not implemented |

#### `control-panel` (32 endpoints; base `/control-panel/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getAllEnrollmentsDeprecated` | GET `/admin/customers` | catalog (sourcemap only) | not implemented |
| `getEnrollmentDeprecated` | GET `/admin/customers/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `getEnrollmentByAuthHeader` | GET `/admin/enrollment-by-auth-header` | catalog (sourcemap only) | not implemented |
| `getEnrollmentCreationInfo` | GET `/admin/enrollment-creation-info` | catalog (sourcemap only) | not implemented |
| `getAllEnrollmentRids` | GET `/admin/enrollment-rids` | catalog (sourcemap only) | not implemented |
| `createEnrollment` | POST `/admin/enrollment/create` | catalog (sourcemap only) | not implemented |
| `getAllEnrollmentInfos` | GET `/admin/enrollment/infos` | catalog (sourcemap only) | not implemented |
| `getEnrollmentInfos` | PUT `/admin/enrollment/infos` | catalog (sourcemap only) | not implemented |
| `getEnrollmentForOrganization` | GET `/admin/enrollment/org/{organizationRid}` | catalog (sourcemap only) | not implemented |
| `getEnrollmentsForOrganizations` | PUT `/admin/enrollment/organizations` | catalog (sourcemap only) | not implemented |
| `updateEnrollment` | PUT `/admin/enrollment/{enrollmentRid}` | catalog (sourcemap only) | not implemented |
| `getEnrollmentApplicationAndExtensionRestrictions` | GET `/admin/enrollment/{enrollmentRid}/application-and-extension-restrictions` | catalog (sourcemap only) | not implemented |
| `createOrganizationInEnrollment` | POST `/admin/enrollment/{enrollmentRid}/create-organization` | catalog (sourcemap only) | not implemented |
| `createOrganizationInEnrollmentForPalantirSupport` | POST `/admin/enrollment/{enrollmentRid}/create-palantir-support-organization` | catalog (sourcemap only) | not implemented |
| `getEnrollmentCreationSettings` | GET `/admin/enrollment/{enrollmentRid}/creation-settings` | catalog (sourcemap only) | not implemented |
| `isCustomerDataAllowed` | GET `/admin/enrollment/{enrollmentRid}/customer-data-allowed` | catalog (sourcemap only) | not implemented |
| `updateEnrollmentHosts` | PUT `/admin/enrollment/{enrollmentRid}/hosts` | catalog (sourcemap only) | not implemented |
| `getEnrollmentHosts` | GET `/admin/enrollment/{enrollmentRid}/hosts/v2` | catalog (sourcemap only) | not implemented |
| `getOrganizationCreationInfo` | GET `/admin/enrollment/{enrollmentRid}/organization-creation-info` | catalog (sourcemap only) | not implemented |
| `assignOrganizationToEnrollment` | PUT `/admin/enrollment/{enrollmentRid}/organization/{organizationRid}/assign` | catalog (sourcemap only) | not implemented |
| `createApolloSpaceForOrganization` | POST `/admin/enrollment/{enrollmentRid}/organization/{organizationRid}/create-apollo-space` | catalog (sourcemap only) | not implemented |
| `createPrivateNamespaceForOrganization` | POST `/admin/enrollment/{enrollmentRid}/organization/{organizationRid}/create-private-namespace` | catalog (sourcemap only) | not implemented |
| `removeOrganizationFromEnrollment` | PUT `/admin/enrollment/{enrollmentRid}/organization/{organizationRid}/remove` | catalog (sourcemap only) | not implemented |
| `registerEnrollmentForDeletion` | PUT `/admin/enrollment/{enrollmentRid}/register-for-deletion` | catalog (sourcemap only) | not implemented |
| `restoreApolloPermissions` | PUT `/admin/enrollment/{enrollmentRid}/restore-apollo-permissions` | catalog (sourcemap only) | not implemented |
| `restoreEnrollmentPermissions` | PUT `/admin/enrollment/{enrollmentRid}/restore-enrollment-permissions` | catalog (sourcemap only) | not implemented |
| `restoreOrganizationPermissions` | PUT `/admin/enrollment/{enrollmentRid}/restore-organization-permissions` | catalog (sourcemap only) | not implemented |
| `setOrganizationInEnrollmentForPalantirSupport` | PUT `/admin/enrollment/{enrollmentRid}/set-palantir-support-organization` | catalog (sourcemap only) | not implemented |
| `unregisterEnrollmentForDeletion` | PUT `/admin/enrollment/{enrollmentRid}/unregister-for-deletion` | catalog (sourcemap only) | not implemented |
| `getEnrollmentForHost` | GET `/admin/hosts/{host}/enrollment-rid` | catalog (sourcemap only) | not implemented |
| `moveOrganizationsAndHosts` | PUT `/admin/move-organizations-and-hosts` | catalog (sourcemap only) | not implemented |
| `createInternalGroupWithAdministrativePermissions` | POST `/admin/organization/{organizationRid}/create-internal-group-with-administrative-permissions` | catalog (sourcemap only) | not implemented |

#### `multipass` (4 endpoints; base `/multipass/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getAllOrganizationMetadatas` | PUT `/organizations/v2/all` | catalog (sourcemap only) | not implemented |
| `getOrganizationMetadatas` | PUT `/organizations/v2/metadata` | catalog (sourcemap only) | not implemented |
| `getOrganizationMetadatasByMarkingId` | PUT `/organizations/v2/metadata/marking` | catalog (sourcemap only) | not implemented |
| `getOrganizationPermissions` | PUT `/organizations/v2/permissions` | catalog (sourcemap only) | not implemented |

#### `foundry-telemetry-service` (15 endpoints; base `/foundry-telemetry-service/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `read` | GET `/containers/{containerRid}/sessions/{sessionId}/logs` | catalog (sourcemap only) | not implemented |
| `getBlobIds` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/blobs/ids` | catalog (sourcemap only) | not implemented |
| `downloadLogsFromBlob` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/blobs/{blobId}/download` | catalog (sourcemap only) | not implemented |
| `download` | GET `/containers/{containerRid}/sessions/{sessionId}/logs/download` | catalog (sourcemap only) | not implemented |
| `downloadV2` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/download/v2` | catalog (sourcemap only) | not implemented |
| `readV2` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/read` | catalog (sourcemap only) | not implemented |
| `readMetadata` | GET `/containers/{containerRid}/sessions/{sessionId}/logs/read/metadata` | catalog (sourcemap only) | not implemented |
| `readV3` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/read/v3` | catalog (sourcemap only) | not implemented |
| `readV4` | POST `/containers/{containerRid}/sessions/{sessionId}/logs/read/v4` | catalog (sourcemap only) | not implemented |
| `getContainerByOwningRid` | GET `/info/containers/by-owning-rid/{owningRid}` | VERIFIED (204) | not implemented |
| `getBatchContainerInfo` | POST `/info/containers/get-batch` | VERIFIED (empty) | not implemented |
| `getContainerAndSessionForOwningRidAndExternalId` | GET `/info/owning-rid/{owningRid}/by-external-id/{externalId}` | catalog (sourcemap only) | not implemented |
| `getBatchSessionAccessInfo` | POST `/info/sessions/access/get-batch` | catalog (sourcemap only) | not implemented |
| `getBatchSessionsByRunRids` | POST `/info/sessions/by-run-rids/get-batch` | catalog (sourcemap only) | not implemented |
| `getBatchSessionInfo` | POST `/info/sessions/get-batch` | VERIFIED (empty) | not implemented |

#### `job-tracker` (5 endpoints; base `/job-tracker/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getBuildsOverview` | POST `/builds` | partial (shape/mount only) (mounted) | not implemented |
| `getBuildsOverviewBulk` | POST `/builds/bulk` | partial (shape/mount only) (mounted) | not implemented |
| `getBuildsOverviewBulkV2` | POST `/builds/bulkV2` | partial (shape/mount only) (mounted) | not implemented |
| `getBuildSummaryOverview` | POST `/builds/summary` | partial (shape/mount only) (mounted; shape unknown) | not implemented |
| `getBuildDetails` | GET `/builds/{buildId}` | partial (shape/mount only) (mounted) | not implemented |

#### `jemma` (8 endpoints; base `/jemma/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `triggerBuild` | POST `/builds` | catalog (sourcemap only) | not implemented |
| `getBuildsForJobs` | POST `/builds/batch/builds-for-jobs` | catalog (sourcemap only) | not implemented |
| `getBuildStatusReports` | POST `/builds/batch/status-report` | VERIFIED (200 {}) | not implemented |
| `getBuildGraph` | GET `/builds/graph` | mounted (times out w/o filter) | not implemented |
| `abortBuild` | POST `/builds/{buildRid}/abort` | catalog (sourcemap only) | not implemented |
| `getFullBuildSummary` | GET `/builds/{buildRid}/full-summary` | catalog (sourcemap only) | not implemented |
| `getCodeScanReport` | GET `/builds/{jobRid}/code-scan-report` | catalog (sourcemap only) | not implemented |
| `getJobStepLogs` | GET `/builds/{jobRid}/{stepNumber}/logs` | catalog (sourcemap only) | not implemented |

#### `object-set-service` (7 endpoints; base `/object-set-service/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `getBulkLinksPage` | PUT `/bulk-links` | catalog (sourcemap only) | not implemented |
| `getLinks` | PUT `/links` | catalog (sourcemap only) | not implemented |
| `getAllObjectsInitialPage` | POST `/objectSets/objects/all/initial` | catalog (sourcemap only) | not implemented |
| `getAllObjectsNextPage` | POST `/objectSets/objects/all/next` | catalog (sourcemap only) | not implemented |
| `getTopObjectsInitialPage` | PUT `/objectSets/objects/top/initial` | catalog (sourcemap only) | not implemented |
| `getTopObjectsNextPage` | PUT `/objectSets/objects/top/next` | catalog (sourcemap only) | not implemented |
| `loadObjects` | PUT `/objects/load` | catalog (sourcemap only) | not implemented |

#### `repository-bootstrapper` (7 endpoints; base `/repository-bootstrapper/api`)

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `bootstrapRepo` | POST `/repos/{repositoryRid}/bootstrap` | catalog (sourcemap only) | not implemented |
| `addChildTemplates` | POST `/repos/{repositoryRid}/child-templates` | catalog (sourcemap only) | not implemented |
| `getTemplates` | GET `/templates` | VERIFIED | not implemented |
| `dryRunRenderTemplateFile` | POST `/templates/render-template` | VERIFIED | not implemented |
| `persistRenderTemplateFile` | PUT `/templates/render-template` | VERIFIED | not implemented |
| `renderTemplateFile` | PUT `/templates/render-template-v2` | VERIFIED | not implemented |
| `getTemplateFilesOfTemplate` | GET `/templates/{templateId}/file-templates` | VERIFIED | not implemented |

#### `authoring-server` (9 endpoints; base `/authoring-server/api`)

> Prefix never located on the verified stack (all candidate prefixes 404).

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `canUseExtension` | GET `/local-dev-access/extension/{repositoryRid}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `canUsePalantirMcp` | GET `/local-dev-access/palantir-mcp` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `canUsePalantirMcpV2` | GET `/local-dev-access/palantir-mcp/v2` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `canUseLocalPreview` | GET `/local-dev-access/preview/{repositoryRid}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `canRefreshToken` | GET `/local-dev-access/refresh-token/{repositoryRid}` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `getGitToken` | POST `/security/gitToken` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `retrieveToken` | POST `/security/token/retrieve` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `storeToken` | POST `/security/token/store` | NOT MOUNTED (this stack) / catalog-only | not implemented |
| `storeProjectToken` | POST `/security/token/store/projects` | NOT MOUNTED (this stack) / catalog-only | not implemented |

#### `log-receiver` (1 endpoints; base `/log-receiver/api`)

> Write-only log ingest; never probed (read-only constraint).

| endpoint | method+path | verified (brain) | pltr-cli status |
|---|---|---|---|
| `logs` | POST `/logs` | NOT MOUNTED (this stack) / catalog-only | not implemented |
### 1b. GraphQL gateway (`POST /graphql-gateway/api/bulk`, SSE transport)

Transport is fully implemented in pltr-cli (`FoundryInternalClient.graphql` / `graphql_bulk`,
out-of-order `requestIndex` demux, single 500-retry, mutation-guarded read-only — shipped with
`pltr notepad get`, PR #8). Introspection is deliberately crippled (20-type stub); the schema
below was recovered via validation-error oracles. `Query` root has 21+ verified fields plus 12
more confirmed from bundles; `Mutation` root exists but is a **thin Compass-navigation surface
only** (`createProject`, `createProjectFromTemplate`, `favorite`, `unfavorite`,
`renameResource`, `moveResources`, `trashResources` — all else `FieldUndefined`).

| operation / root field | what it returns | verified (brain) | pltr-cli status |
|---|---|---|---|
| `me` | current user | VERIFIED | internal (transport smoke) |
| `resourceMetadata(rid:)` | universal RID→name/path/type/parent/created/modified/permissions resolver | VERIFIED | not implemented (planned; `pltr dependency` uses Compass ACP-08 namer instead) |
| `objectTypeV2(identifier:)` + `.dependents` | object type core + **dependents** (Workshop modules, link types) — **no pageToken arg; truncates silently** | VERIFIED | wrapped via `pltr dependency object-type` (U6/ACP-05, PR #10) |
| `objectType(rid:)`, `objectTypeById(id:)` | object type by rid / by id | VERIFIED (id form from bundle) | not implemented |
| `objectTypesV2(pageSize:, filter:, pageToken:)` | paginated object-type list w/ display names | VERIFIED | not implemented |
| `linkType(rid:)`, `linkTypes(pageSize:)` | link types | VERIFIED | not implemented |
| `actionType(rid:)` + `.dependents(pageToken:)` | action-type dependents — **paginates correctly** (asymmetric with objectType) | VERIFIED | not implemented |
| `actionTypes(pageSize:, filter:{ruleTypes:[FUNCTION], functionRid})` | **function → action-types** reverse edge | VERIFIED callable (empty for probe) | not implemented (planned Phase B) |
| `function(rid:)`, `functions(pageSize:)` | function list/detail; `FunctionVersion.usageHistory` | list VERIFIED; usageHistory UNVERIFIED | not implemented |
| `ontology(rid:)`, `ontologyBranch(rid:)` | ontology metadata | VERIFIED | not implemented |
| `schedule(scheduleRid:)`, `schedules(pageSize:, filter:)` | schedule search; filter by `buildDatasets`/`affectedDatasets`/`inputDatasetRids`/`affectedProjects`/`projectRids`/`userIds`; **`totalNumberOfResultsV2` = free server-side blast-radius count** | VERIFIED (34 stack-wide) | not implemented |
| `build(buildRid:)`, `job(rid:)`, `jobs(pageSize:, filter:)` | build/job reports | VERIFIED (root fields) | not implemented |
| `search(title:, limit:)` | fast title search, all resource types | VERIFIED | not implemented |
| `searchResources(filter:, sort:, pageSize:)` | full resource search w/ highlights (`pathStartsWith` verified) | VERIFIED | not implemented |
| `notepad(rid:)` + `latestVersion.contents` | full notepad body (Slate JSON) + embedded references | VERIFIED | wrapped via `pltr notepad get` (PR #8, #9) |
| `principal(id:)` | user/group resolution | VERIFIED (root field) | not implemented |
| `collections`, `projectPortfolio`, `notifications`, `favorites`, `recents` | user/workspace state | confirmed exist (bundle + live re-verify) | not implemented |
| `globalBranch(rid:)`, `defaultOrGlobalBranch(identifier:)` | Global Branching | exist; resolve nothing (no live global branch on stack) | not implemented |
| `resourceMetadata(rid).objectSetMonitors` | **resource → automations (monitors)** reverse edge | VERIFIED callable (`null` for probe) | not implemented |
| `NumberOfSchedulesColorSchemeQuery` | dataset → # schedules (server count) | VERIFIED | not implemented |
| `GetObjectTypeDependents` | the primary impact query | VERIFIED | wrapped via `pltr dependency` (U6) |
| `GetNotepadContentsQuery` | notepad contents | VERIFIED | wrapped via `pltr notepad get` |

### 1c. Public `/api/v2` surface (documented; via `foundry-platform-sdk` pin)

Not enumerated endpoint-by-endpoint here (the SDK is self-documenting); cataloged by area.
Key live-verified addition: `GET /api/v2/ontologies/{ont}/objectTypes/{apiName}?includeDatasources=true`
(property→column mapping) — **public**, retires stale CAP-14; wrapped by `pltr dependency` (ACP-04).

| area | public surface | pltr-cli status |
|---|---|---|
| Datasets, files, branches, transactions | `dataset.*` | wrapped via `pltr dataset`, `pltr cp` |
| Filesystem (folders, projects, spaces, resources, references) | `folder/project/space/resource` | wrapped via `pltr folder/project/space/resource`, `project imports` |
| Ontology (object/link/action types, objects, queries, interfaces) | `ontology.*` | wrapped via `pltr ontology` |
| Orchestration (builds, jobs, schedules) | `orchestration.*` | wrapped via `pltr orchestration` (schedules ≤1hr stale via `Dataset.get_schedules`) |
| SQL queries | `sql.*` | wrapped via `pltr sql` |
| Media sets | `mediasets.*` | wrapped via `pltr media-sets` |
| Connectivity (connections, table imports) | `connectivity.*` | wrapped via `pltr connectivity` |
| Third-party applications | `thirdPartyApplications.*` | wrapped via `pltr third-party-apps` (read subset) |
| AIP agents | `aipAgents.*` | wrapped via `pltr aip-agents` |
| Functions / value types | `functions.*` | wrapped via `pltr functions` |
| Streams | `streams.*` | wrapped via `pltr streams` |
| Language models | `languageModels.*` | wrapped via `pltr language-models` |
| ML models | `models.*` | wrapped via `pltr models` |
| Data health | (SDK surface) | wrapped via `pltr data-health` |
| Audit logs | `audit.*` | wrapped via `pltr audit` |
| Widget sets | `widgets.*` | wrapped via `pltr widgets` |
| Admin (users, groups, orgs, enrollments) | `admin.*` (multipass/control-panel public) | wrapped via `pltr admin` |
| Proposals / global branching / PRs | **none in pinned SDK** (`SDK_REACHABLE_CAPABILITIES` = ∅) | `pltr proposal` modeled but **no backing** — needs internal `branch-service` + `stemma-pull-request` |
| Namespaces | **no public list operation** | `pltr namespace` blocked (explicit gap, CAP ledger) |
| Project templates | **no public catalog** | blocked (explicit gap) |
| Lineage / reverse dependencies | **none** (forward-declarative only) | `pltr lineage` = folder-containment floor; `pltr dependency` = internal-API ceiling |

---

## 2. Gap matrix — Foundry functional area × pltr-cli coverage

Coverage: ✅ covered · ◐ partial · ❌ not covered · ⛔ no known API (verified gap).

| functional area | app shell (`/workspace/…`) | API surface available | pltr-cli | notes |
|---|---|---|---|---|
| Compass file browser / projects | `compass` | public + internal compass (153 ep) | ✅ | batch/bulk namer (N+1 fix) unimplemented |
| Compass search | hubble/compass | GraphQL `search`/`searchResources` | ❌ | VERIFIED; trivial to add (transport exists) |
| Ontology Manager (Object Explorer) | `hubble` | GraphQL ontology fields + ontology-metadata (65 ep) | ◐ | read via SDK; internal search/diff/dry-run unimplemented |
| Datasets / catalog | compass | public + `foundry-catalog` (51 ep) | ✅ | read+write via SDK/orchestration |
| Data lineage | `monocle` | monocle V3 (12 ep, VERIFIED) | ◐ | graphV3 corroboration-only inside `pltr dependency`; no standalone `lineage --internal` BFS |
| Pipeline Builder (eddie) | (via compass) | `ri.eddie.main.pipeline.*` resources | ❌ | name via Compass only; no pipeline-definition API found |
| Code Repositories (transforms) | `code` | stemma (43 ep) + repository-contents (19 ep) | ◐ | ACP-03 file contents inside dependency; no `pltr repo browse/tree/blame` |
| Code Workspaces / authoring | — | `authoring-server` (9 ep) | ⛔ | prefix never located; local-dev/git-token plumbing only |
| Pull requests (code review) | `code` | `stemma-pull-request` (29 ep) | ❌ | VERIFIED in catalog; the real backing for `pltr proposal` |
| Global Branching / proposals | — | `branch-service` (23 ep) | ❌ | enabled but unused on test stack; response shapes mostly UNVERIFIED |
| Builds / jobs / schedules | `job-tracker`, `scheduler` | build2 BuildInfo (19 ep), job-tracker, jemma, public orchestration | ◐ | public SDK wrapped; internal reports/job-tracker not; **no internal scheduler service mounted** (⛔) — GraphQL `schedules` is the non-stale replacement |
| Data Health / monitoring | `data-health` | `foundry-datahealth` (46 ep) + public | ◐ | `pltr data-health` (SDK); per-dataset check reverse index (`/checks/v2/{rid}/{branch}`) unimplemented |
| Object Sentinel / automations | — | GraphQL `objectSetMonitors`; monitors = Compass resources | ❌ | no standalone sentinel service exists (verified) |
| AIP (Logic, Agents, semantic search) | `aip` | `language-model-service` (15 ep), function-registry locators, public aip-agents | ◐ | semantic index list VERIFIED (empty on stack); index reverse edge UNVERIFIED |
| Functions | `functions` | `function-registry` (38 ep) + public | ◐ | usageHistory (fn→consumers) VERIFIED, unimplemented |
| Workshop | `apps`, object views | **no read API mounted** (⛔ variables); modules appear as GraphQL dependents + Compass resources | ◐ | consumers visible via `pltr dependency object-type`; module internals not readable (documented gap) |
| Slate | `slate` | none mounted (SPA only) | ⛔ | name via Compass only |
| Carbon (home) | `carbon` | none found | ⛔ | |
| Quiver (time series) | `quiver` | none mounted; notepad quiver-* widgets (bundle-derived) | ⛔ | name via Compass only |
| Contour | (via notepad plugin) | none found | ⛔ | name via Compass only |
| Fusion (spreadsheet) | `fusion` | none found | ⛔ | |
| Maps / Vertex | `map` | none found | ⛔ | name via Compass only |
| Notepad | `notepad` | GraphQL `notepad(rid:)` | ✅ | `pltr notepad get` shipped; object-widget configs bundle-derived (unclosable on test stack) |
| Marketplace (block sets) | `marketplace` | none mounted | ⛔ | name via Compass only; no install/manifest API |
| Dossier | — | none found in any sweep | ⛔ | |
| Taurus / Foundry Rules | `foundry-rules` | GraphQL ops harvested from its bundle | ❌ | rules types not on gateway; `actionTypes(filter:{ruleTypes:…})` partially relevant |
| Developer Console / OSDK apps | `developer-console` | `third-party-application-service` (48 ep) | ◐ | SDK read subset (`pltr third-party-apps`); **OSDK pin / per-entity SDK ranges unimplemented (U7 planned)** |
| Compute modules / deployed apps | — | `module-group` (34 ep) | ⛔ | NOT MOUNTED on gateway (all prefixes `Route:RouteNotMounted`) |
| Data connections / sources | (connectivity UI) | `magritte-coordinator` (34 ep) + public | ◐ | public `pltr connectivity`; internal source inventory VERIFIED, unimplemented; **source→dataset sync edge is a verified GAP** (use build2 provenance) |
| Webhooks | — | `webhooks` (20 ep) | ❌ | source↔webhook both directions VERIFIED; unimplemented |
| Network egress policies | — | `resource-policy-manager` (26 ep) | ❌ | catalog-only; approval workflow noted |
| Multipass / identity | — | `multipass` (4 ep) + public admin | ✅ | orgs/principals via `pltr admin` |
| Control panel (enrollments/orgs/hosts) | — | `control-panel` (32 ep) | ◐ | public admin subset; enrollment detail VERIFIED internal, unimplemented |
| Comments | — | `comments` (14 ep) | ❌ | batch counts VERIFIED (weak "watched" signal) |
| Object sets (execution) | — | `object-set-service` (7 ep) | ❌ | mounted; request proto UNVERIFIED — prefer public OSDK object queries (`pltr ontology`) |
| Telemetry / build logs | — | `foundry-telemetry-service` (15 ep) | ❌ | container/session/log reads VERIFIED prefix |
| Metadata KV store | — | `foundry-metadata` (28 ep) | ❌ | permission-gated; `/metadata/events` global change feed noted |
| Repo bootstrapper (templates) | — | `repository-bootstrapper` (7 ep) | ❌ | templates list VERIFIED |
| Usage / billing | — | **none found** in 27 services | ⛔ | no usage/billing endpoint in MCP catalog or sweeps |

---

## 3. Prioritized addition list

Ranked for an agent-facing CLI. All read-only. Each notes the endpoint(s) and brain
verification status. "Transport exists" = `FoundryInternalClient` already implements Conjure
REST + GraphQL-SSE, so the marginal cost is a collector + command.

| # | proposed command | endpoint(s) used | verified? | value |
|---|---|---|---|---|
| 1 | `pltr search <text>` — cross-resource search | GraphQL `search(title:)`, `searchResources(filter:)` | VERIFIED | transport exists; highest-frequency agent need; replaces Compass GUI |
| 2 | `pltr resource describe <rid>` — universal namer/resolver | GraphQL `resourceMetadata(rid:)`; batch via `POST /compass/api/batch/resources` (shape UNVERIFIED) | VERIFIED (single) | decorates every bare-RID output (dependency, lineage, usage); N+1 fix |
| 3 | `pltr lineage graph <rid> --internal` — true reverse lineage BFS | monocle `graphV3` / `hierarchyV3` / `intersectionV3` | VERIFIED | fixes the known false parity claim (`get_resource_graph` ≈ folder containment); V3 preferred over dead V2 |
| 4 | `pltr schedules affected-by <dataset-rid>` — blast-radius count in one call | GraphQL `schedules(filter:{buildDatasets/affectedDatasets/inputDatasetRids})` + `totalNumberOfResultsV2` | VERIFIED | only free server-side reverse count; replaces 1-hr-stale `Dataset.get_schedules` |
| 5 | `pltr actions dependents <action-type-rid>` | GraphQL `actionType(rid:).dependents(pageToken:)` (paginates correctly) | VERIFIED | completes the dependents family; note the objectType truncation asymmetry (object-type dependents >1 page = inconclusive) |
| 6 | `pltr functions usage <function-rid>` — who calls this function, per version | `GET /function-registry/api/functions/{rid}/usageHistory`; fn→action-types via `actionTypes(filter:{ruleTypes:[FUNCTION],functionRid})` | VERIFIED / VERIFIED-callable | crosses into Workshop + Object Sentinel; closes CAP-16 |
| 7 | `pltr apps sdk-versions <app-rid>` — which apps break on a rename (U7) | TPAS `GET /applications[/{rid}]`, `GET /application-sdks/{rid}`, `PUT …/entity-sdk-versions` | VERIFIED | exact OSDK-pin impact signal; already planned (dependency U7) |
| 8 | `pltr dependency dataset <rid>` — dataset up/downstream transform walk | `POST /build2/api/jobspecs/branches/{b}/{upstream,downstream,connecting}-jobspecs` (+ `branchFallbacks`) | VERIFIED | completes south-plane traversal; ACP-02 specs already registered |
| 9 | `pltr dataset checks <rid>` — what assertions guard this dataset | `GET /data-health/api/checks/v2/{datasetRid}/{branchId}`, `…/available`, reports/state reads | VERIFIED (empty fixtures) | schema-change breakage vocabulary; bulk variant field name UNVERIFIED |
| 10 | `pltr ontology actions-for <object-type>` | `PUT /ontology-metadata/api/ontology/ontology/actionTypesForObjectType` (note: returns ObjectTypeIds, not RIDs) | VERIFIED | object→action reverse index; closes CAP-06/CAP-10 remainder |
| 11 | `pltr dataset backed-entities <rid>` | `POST /ontology-metadata/api/ontology/ontology/bulkLoadEntitiesByDatasources` (tagged-union body) | VERIFIED | dataset→ontology reverse index; pairs with ACP-04 |
| 12 | `pltr project imports <rid>` / `imported-by <rid>` | compass `/projects/imports/{rid}/rids`, `/importing-projects`, `/context` | VERIFIED | silent-permission filtering must surface as inconclusive |
| 13 | `pltr connections list` / `source get` — internal source inventory | magritte `/source-store/sources/{rids,descriptions,types}`, `/source/{id}/{config,agents}` | VERIFIED | never call `getSourceConfigWithPlaintextSecretValues` |
| 14 | `pltr webhooks list` / `for-source <source-rid>` | webhooks `/registry/v0/webhooks-getRidsForSources`, `/{rid}/latest` | VERIFIED | external downstream consumers; definition back-references sourceRid |
| 15 | `pltr repo browse/tree/blame <repo-rid>` | stemma `GET /repos`, `/repos/{rid}/paths/tree/`, `/paths/contents/{path}`, blame | VERIFIED | code→dataset provenance companion (ACP-03 partial already) |
| 16 | `pltr ontology list-types --display` — human-readable ontology inventory | GraphQL `objectTypesV2` / `linkTypes` / `actionTypes` / `functions` (paged) | VERIFIED | SDK gives apiNames; GraphQL adds display names/status union |
| 17 | `pltr proposal` real backing | `stemma-pull-request` (`getApprovalResult`, `getMergeInfo`, `getRequiredChecksForBranches`) + `branch-service` (`checkProposalDeployable`, `getResourceDependencyGraph`) | endpoints VERIFIED in catalog; live PR read UNVERIFIED; dependency-graph contract-only | `pltr proposal` currently has zero SDK reachability — this is the only real implementation path |
| 18 | `pltr ontology diff/dry-run` — pre-edit preview (read-only) | `POST /ontology/v2/modify/dry-run`, `/ontology/v2/{ont}/diff`, branch `findConflicts`/`validate`/`merge/dry-run` | partial (reachable; contracts UNVERIFIED) | native change-preview evidence |
| 19 | `pltr builds report <build-rid>` / `job logs` | build2 BuildInfo (`/info/builds2/{rid}`, `/info/jobs3/{rid}`), job-tracker `/builds/{id}`, jemma `full-summary`, telemetry logs | job-tracker/telemetry prefix VERIFIED; build-info catalog-only | "did my change break a build" read |
| 20 | `pltr automations of <rid>` — monitors watching a resource | GraphQL `resourceMetadata(rid).objectSetMonitors` | VERIFIED callable | only automation reverse edge that exists |
| 21 | `pltr semantic-indexes list` | `GET /language-model-service/api/semantics/v1/indexes` | VERIFIED (empty on stack) | AIP/RAG consumers of datasets; reverse edge UNVERIFIED |
| 22 | `pltr notepad list` — enumerate notepads | GraphQL `searchResources(filter:{pathStartsWith:…})` + type filter | VERIFIED | complements `notepad get`; object-type→notepad edge proven NOT to exist — must enumerate via Compass |

Deliberately **not** proposed (no read path): Workshop module internals/variables, Slate/Quiver/
Contour/Fusion/Maps/Dossier/Marketplace contents (Compass namer only), compute-module bindings
(module-group not mounted), source→synced-dataset edge (use build2 provenance), usage/billing.

---

## 4. Known gaps and impossibles (explicit, do not paper over)

1. **Workshop variables / module internals are not readable.** `/workshop/api/*` and
   `module-group-api` both return `Route:RouteNotMounted` on the verified stack. Compass names
   a module and gives its path, nothing more. Permanent gap unless a non-gateway route emerges.
2. **Project-template catalog: blocked** (capability ledger). SDK exposes
   `create_from_template` + `ProjectTemplateRid` but no template-list operation; no internal
   equivalent found either.
3. **Namespace listing: blocked** (capability ledger). `Space.list` exists but no Namespace
   resource/list operation in SDK 1.95.0; `namespace` command is an explicit fallback.
4. **Source → synced-dataset lineage does not exist in magritte.** Source configs carry empty
   `resources`/`connections`; resolve the edge from the output dataset's build2 jobspec /
   transaction provenance instead.
5. **No internal scheduler service is mounted** (`/orchestration`, `/scheduler`,
   `/build2/.../schedules` all 404). Non-stale schedule reads exist **only** via GraphQL
   `schedules(...)` (see addition #4).
6. **`objectTypeV2.dependents` truncates silently** — no `pageToken:` argument (unlike
   `actionType.dependents`). Object-type dependents beyond page 1 are *inconclusive*, never
   "few dependents". Prefer monocle for object-type reverse edges at scale.
7. **`ObjectType.dependents` does NOT surface notepads** (verified across all 96 object types).
   Notepads must be enumerated via Compass, not via dependents.
8. **Notepad object-reference widget configs are bundle-derived**, not live-verified — a
   100%-population sweep (all 12 notepads) found only compass-resource + image widgets. Needs
   a stack with a real object-referencing notepad to close.
9. **GraphQL `Mutation` root is Compass-navigation only** (7 fields). All semantic mutations
   go through internal Conjure REST — any future gate must sit at the Conjure layer.
10. **GraphQL introspection is deliberately crippled** (20-type stub). Schema knowledge comes
    from validation-error oracles; a full schema dump is not achievable.
11. **branch-service dependency-graph response shape UNVERIFIED** — Global Branching is enabled
    but has no live branches on the test stack; no list-branches endpoint exists.
12. **build2 `get-branches` second required field unknown** (~120 candidates rejected);
    `-nodes` endpoint variants always return `[]`. Use `GET /jobspecs/datasets/{rid}` instead.
13. **build2 jobspec events need a service-root permission** — not viable from a user token.
14. **Object Sentinel has no dedicated service** — monitors are Compass resources +
    GraphQL `objectSetMonitors` only.
15. **federatedLink / provenanceLink / mlLink monocle payloads unknown** (never emitted in a
    26-RID BFS). Decode defensively, preserve raw payload.
16. **Unknown request fields are silently ignored** on ontology-metadata/compass (200 + empty
    results). A `200` is never validation; every consumer needs a positive control.
17. **Permissions produce empty, not 403** (compass imports, notepad reads return
    `null`/filtered at HTTP 200). Empty ≠ none; report as inconclusive.
18. **No usage/billing endpoints exist** in the 27-service catalog or any sweep.
19. **Slate, Quiver, Contour, Fusion, Maps/Vertex, Dossier, Marketplace, Carbon**: no API
    surface found (no mounted service; no GraphQL types — `Quiver`, `Slate`, `Contour`,
    `Fusion` are confirmed-absent type names on the gateway). Compass namer only.
20. **Stability warning**: none of the internal surface is supported. Palantir stated publicly
    (2026-06-23) that Workflow Lineage exposes no public lineage APIs. Pin `@palantir/mcp`
    v0.397.0 contracts, shape-check every response, degrade loudly.
