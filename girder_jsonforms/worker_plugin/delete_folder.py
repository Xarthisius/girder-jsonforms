from girder.models.folder import Folder
from girder.models.user import User
from girder.utility.progress import ProgressContext
from girder_worker.app import app


@app.task(queue="local")
def run(
    folderId: str,
    progress: bool,
    userId: str,
    contentsOnly: bool = False,
):
    user = User().load(userId, force=True)
    folder = Folder().load(folderId, force=True)
    if not folder:
        return

    with ProgressContext(
        progress,
        user=user,
        title=f'Deleting folder {folder["name"]}',
        message="Calculating folder size...",
    ) as ctx:
        if progress:
            total = Folder().subtreeCount(folder)
            if contentsOnly:
                total -= 1
            ctx.update(total=total)

        if contentsOnly:
            Folder().clean(folder, progress=ctx)
        else:
            Folder().remove(folder, progress=ctx)
