# After Effects folder workflows

Run these workflows on a self-hosted n8n on this Mac. n8n Cloud cannot see your disk. n8n Cloud cannot start After Effects.

These files are local tools. Keep them out of git.

## Duplicate a folder from a name and an id

Import [duplicate-by-name.json](duplicate-by-name.json) again after this file changes. The form asks for a name, an id, and the clip path. Keep the form page open. The operator app can also POST the same fields to `/webhook/influencer`, plus `progressUrl` and `progressToken`. Each line is posted there while the run is still going, so the waiting page can show it. Docker n8n cannot start After Effects, so that workflow calls the Mac API and the Mac runs the script. The workflow uploads that mp4 or mov to https://greenkey.mxjprod.work and waits for the alpha movie. It then copies `ss-influencer`, writes the name and the id, puts the alpha movie in the copy, and opens the copy in After Effects. The same page then shows the new folder.

The template folder is `/Users/glaucomp/Desktop/PackageMaker/ss-influencer`. Each run creates a new folder under `/Users/glaucomp/Desktop/PackageMaker/jobs`. The folder name is `SS-`, then the id, then `|`, then the name. Id `234` and name `Glauca` create `SS-234|Glauca`. The template folder stays unchanged.

The copy stores the name in `InfluencerName` and the id in `cardNumberText` inside `(Footage)/influencer/data.json`. The workflow opens the Greenkey alpha movie in After Effects. After Effects then relinks footage to the copied files and reads that data file.

Change the template path, the jobs path, or the project file name in the **Copy and edit** node when you use another template. Change the After Effects path in **Start After Effects** when you use another version.

Quit After Effects before each run. The clip uploads to https://greenkey.mxjprod.work. Greenkey returns one alpha movie. The workflow saves that movie as `(Footage)/influencer/influencer_alpha.mov` in the copy and opens it in After Effects. Authentik login uses an app password in `~/Desktop/PackageMaker/api_token` and the username in `~/Desktop/PackageMaker/api_user`. An Authentik API token is not accepted. Delete the job folder when you want to run the same name and id again. The copy step stops when that folder already exists.

## Duplicate, rename, and relink any folder

Import [duplicate-rename-relink.json](duplicate-rename-relink.json) when you need to choose both paths and a file-name replacement. The workflow copies a folder, renames files, and opens the copied After Effects project. After Effects relinks footage to the copied files.

## Allow the Execute Command node

n8n does not load the Execute Command node by default. Start this repository with the node allowed:

```bash
NODES_EXCLUDE='[]' pnpm dev:be
```

Use that setting only on a private instance on this Mac. The Execute Command node runs shell commands.

## Import a workflow

1. Open n8n.
2. Import the workflow JSON.
3. Open the form from **On form submission**. In test mode, execute the workflow and use the test form. For repeated runs, publish the workflow and open the production form URL.

## Before each run

Quit After Effects. When After Effects is already open, the launch command does not control that instance.

Delete the destination folder when an earlier run created it. The copy step stops when the destination already exists.

## Form fields for the manual workflow

| Field | Purpose |
| --- | --- |
| Source folder | Template folder. |
| Destination folder | New folder path. The folder must not exist. |
| Text to find in file names | Text that appears in file names. Leave this empty to copy the folder and relink footage with the current names. |
| Replacement text | Text that replaces each match. The form removes spaces at the start and end of every text field. |
| Project file name | File name or relative path inside the folder, such as `template.aep`. The default is `template.aep`. |
| After Effects binary | Mac program inside the application package. The default path is After Effects 2025. Change the year when you use another version. In Finder, open the application package and use the file in `Contents/MacOS`. |

## What the workflow does

1. **Copy folder.** `ditto` copies the source folder. The step stops when the source is missing, the destination exists, or one folder is inside the other.
2. **Rename files and write JSX.** Every file whose name contains the find text gets a new name, at any depth. The project file is included when its name matches. The step refuses a rename that gives two files the same name, including names that differ only by letter case. It writes `ae-relink.jsx` and `ae-relink-report.json` in the destination folder.
3. **Start After Effects.** The step starts After Effects with the JSX file. After Effects opens the copied project, relinks footage, saves the project, and stays open.

The script matches each footage item in this order:

1. The stored path is the file in the template folder.
2. The stored path is the copied file before the rename.
3. The file name matches one file in the copy.

Solids, compositions, and other items without a file stay unchanged. A dialog lists footage the script could not relink. The same text is in `ae-relink-result.txt` next to the project file. The launch log is `ae-launch.log` in the destination folder.

## Check

Run the workflow once with After Effects quit. Confirm the template folder is unchanged. Confirm the open project uses files from the destination folder.
