import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout

from app.api.routes import router
from app.config import ROOT, Settings
from app.database import Database
from app.workers.job_worker import Worker
from app.v2 import clips, runs, security, studio
from app.v2.storage import migrate, seed


def worker_lock(settings: Settings) -> FileLock:
    return FileLock(str(settings.root / "data" / "worker.lock"), timeout=0)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings.prepare()
        lock = worker_lock(settings)
        try:
            lock.acquire()
        except Timeout as exc:
            raise RuntimeError("MOMENTRIX already has a worker for this data directory") from exc
        logger = logging.getLogger("momentrix")
        sink = RotatingFileHandler(settings.root / "logs" / "momentrix.log", maxBytes=1_000_000,
                                   backupCount=2, encoding="utf-8")
        sink.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(sink)
        logger.setLevel(logging.INFO)
        try:
            database = Database(settings.root / "data" / "jobs.sqlite3")
            database.initialize()
            migrate(database)
            database.recover_interrupted()
            seed(settings,database)
            application.state.database = database
            worker = Worker(settings, database)
            worker.studio_enabled = True
            application.state.worker = worker
            worker.thread.start()
            try:
                yield
            finally:
                worker.stop.set()
                worker.wake.set()
                await asyncio.to_thread(worker.thread.join)
        finally:
            logger.removeHandler(sink)
            sink.close()
            lock.release()

    application = FastAPI(title="MOMENTRIX", version="2.0.0", lifespan=lifespan)
    application.state.settings = settings

    application.middleware("http")(security.guard)
    application.include_router(router)
    for group in (security.router, studio.router, runs.router, clips.router):
        application.include_router(group, prefix="/api/v2")
    @application.get("/", include_in_schema=False)
    def website():
        return RedirectResponse("/studio/")
    application.mount("/studio", StaticFiles(directory=ROOT / "frontend" / "dist", html=True, check_dir=False), name="studio")
    return application


app = create_app()
