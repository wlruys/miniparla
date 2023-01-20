#include "cpp_runtime.hpp"

#include <chrono>
#include <fstream>
#include <iostream>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

#ifdef PARLA_LOGGING
#include <binlog/binlog.hpp>

int log_write(std::string filename) {
  std::ofstream logfile(filename.c_str(),
                        std::ofstream::out | std::ofstream::binary);
  binlog::consume(logfile);

  if (!logfile) {
    std::cerr << "Failed to write logfile!\n";
    return 1;
  }

  std::cout << "Log file written to " << filename << std::endl;
  return 0;
}

#else

int log_write(std::string filename) { return 0; }

#endif


//Input: PythonTask
//Explaination: Call python routine to attempt to grab a worker thread, assign a task to it, and then notify the thread.
//Output: If no worker thread is available, return false. Otherwise, return true.
void launch_task_callback(callerfunc func, void* f, void* task, void* worker) {
    //std::cout << "launch_task_callback" << std::endl;
    func(f, task, worker);
    //std::cout << "launch_task_callback done" << std::endl;
    return;
}

void launch_stop_callback(stopfunc func, void* f) {
    ////std::cout << "launch_stop_callback" << std::endl;
    return func(f);
}

//InnerTask Class Methods

InnerTask::InnerTask() {
    this->id = 0;
    this->task = NULL;
    this->vcus = 0.0;

    this->dependencies = std::vector<InnerTask*>();
    this->num_deps = 0;
    this->dependents = std::vector<InnerTask*>();
}

InnerTask::InnerTask(long id, void* task, float vcus) {
    this->id = id;
    this->task = task;
    this->vcus = vcus;

    this->dependencies = std::vector<InnerTask*>();
    this->dependents = std::vector<InnerTask*>();

    this->num_deps = 0;
}

void InnerTask::set_task(void *task) { this->task = task; }

void InnerTask::set_name(std::string name) { this->name = name; }

void InnerTask::set_type_unsafe(int type){
    this->type=type;
}

void InnerTask::set_type(int type){
    this->m.lock();
    this->set_type_unsafe(type);
    this->m.unlock();
}

void InnerTask::add_dependency_unsafe(InnerTask* task) {
    if (task->add_dependent(this)){
        ////std::cout << "Adding dependency " << task->id << std::endl;
        this->dependencies.push_back(task);
        this->num_deps++;
    }
    //std::cout << "Num deps: " << this->num_deps << std::endl;
}

void InnerTask::add_dependency(InnerTask* task) {
    auto& msg = my_registered_string::get<add_dependency_msg>();
    my_scoped_range r{msg}; 
    this->m.lock();
    //std::cout << "add_dependency (c++) " << this->num_deps << std::endl;
    this->add_dependency_unsafe(task);
    this->m.unlock();
}

void InnerTask::add_dependencies(std::vector<InnerTask*> task_list){
    this->m.lock();
    for (int i = 0; i < task_list.size(); i++) {
        this->add_dependency_unsafe(task_list[i]);
    }
    this->m.unlock();
}

void InnerTask::clear_dependencies(){
    this->m.lock();
    this->dependencies.clear();
    this->m.unlock();
}

bool InnerTask::blocked(){
    this->m.lock();
    bool blocked = this->num_deps > 0;
    this->m.unlock();
    return blocked;
}

int InnerTask::get_num_deps(){
    this->m.lock();
    int num_deps = this->num_deps;
    this->m.unlock();
    return num_deps;
}

bool InnerTask::blocked_unsafe(){
    return this->num_deps > 0;
}

bool InnerTask::add_dependent(InnerTask* task){

    auto& msg = my_registered_string::get<add_dependent_msg>();
    my_scoped_range r{msg}; 

    this->m.lock();
    if (this->complete){
        //std::cout << "Task " << this->id << " is already complete" << std::endl;
        this->m.unlock();
        return false;
    }
    else{
        this->dependents.push_back(task);
        //std::cout << "Task " << this->id << " is NOT COMPLETE" << std::endl;
        this->m.unlock();
        return true;
    }
}

void InnerTask::notify_dependents(InnerScheduler* scheduler){
  LOG("Finished Task {}", this->name);

  auto& msg = my_registered_string::get<notify_msg>();
  my_scoped_range r{msg}; 

  // std::cout << "notify_dependents " << this->id << std::endl;
  this->complete = true;
  for (int i = 0; i < this->dependents.size(); i++) {
    bool notify = this->dependents[i]->notify();
    // std::cout << "notify_status " << notify << std::endl;
    if (notify) {
      // std::cout << "Enqueueing task" << std::endl;
      scheduler->enqueue_task(this->dependents[i]);
    }
    }
    this->m.unlock();
}

bool InnerTask::notify(){
    //std::cout << "Task is being notified" << this->num_deps << std::endl;
    this->m.lock();
    int deps = --this->num_deps;
    this->m.unlock();
    bool condition = (deps == 0);
    //std::cout << "Task has been notified" << condition << std::endl;
    return condition;
}

//InnerScheduler Class Methods

InnerScheduler::InnerScheduler() {
    this->func = NULL;
    this->resources = 1;
    this->active_tasks = 1;
    this->running_tasks = 0;

    this->ready_queue = std::vector<InnerTask *>();

    this->free_threads = 0;
}

InnerScheduler::InnerScheduler(callerfunc call, float resources, int nthreads) {
    this->call = call;
    this->resources = resources;
    this->active_tasks = 1;
    this->running_tasks = 0;

    this->ready_queue = std::vector<InnerTask *>();
    this->free_threads = 0;
}

void InnerScheduler::set_python_callback(callerfunc call, stopfunc py_stop, void* f) {
    ////std::cout << "set_python_callback" << std::endl;
    this->func = f;
    this->call = call;
    this->py_stop = py_stop;
}

void InnerScheduler::set_resources(float resources) {
    this->resources_mutex.lock();
    this->resources = resources;
    this->resources_mutex.unlock();
}

void InnerScheduler::set_nthreads(int nthreads) {
    this->free_threads_mutex.lock();
    this->free_threads = nthreads;
    this->free_threads_mutex.unlock();
}

void InnerScheduler::enqueue_worker(InnerWorker *worker) {
  this->thread_queue_mutex.lock();
  this->thread_queue.push_back(worker);
  this->thread_queue_mutex.unlock();

  this->free_threads++;
}

InnerWorker *InnerScheduler::dequeue_worker() {
  my_scoped_range r("Dequeue Worker", nvtx3::rgb{0,255,0});
  this->thread_queue_mutex.lock();
  // std::cout << "thread_queue size: " << this->thread_queue.size()
  //<< this->free_threads << std::endl;
  InnerWorker *worker = this->thread_queue.back();
  this->thread_queue.pop_back();
  this->thread_queue_mutex.unlock();
  this->free_threads--;

  return worker;
}

//Enqueue a task to ready (Safe/Unsafe)
void InnerScheduler::enqueue_task(InnerTask* task){
    my_scoped_range r("Enqueue Task", nvtx3::rgb{255,0,0});
    this->ready_queue_mutex.lock();
    this->ready_queue.push_back(task);
    this->ready_queue_mutex.unlock();
    this->ready_tasks++;
    this->has_update();
}

void InnerScheduler::enqueue_task_unsafe(InnerTask* task){
  this->ready_queue.push_back(task);
  this->ready_tasks++;
  this->has_update();
}

float InnerScheduler::get_resources_next() {
  // this->ready_queue_mutex.lock();
  InnerTask *task = this->ready_queue.back();
  // this->ready_queue_mutex.unlock();
  return task->vcus;
}

//Dequeue a task from ready (Safe/Unsafe)
InnerTask* InnerScheduler::dequeue_task(){

    my_scoped_range r("Dequeue Task", nvtx3::rgb{255,0,0});
    this->ready_queue_mutex.lock();
    InnerTask *task = this->ready_queue.back();
    this->ready_queue.pop_back();
    this->ready_queue_mutex.unlock();
    this->ready_tasks--;
    if (task == NULL) {
      std::cout << "Task is NULL" << std::endl;
    }
    return task;
}

InnerTask* InnerScheduler::dequeue_task_unsafe(){
  InnerTask *task = this->ready_queue.back();
  this->ready_queue.pop_back();
  this->ready_tasks--;
  return task;
}

int InnerScheduler::get_ready_queue_size(){
    my_scoped_range r("Get Queue Size", nvtx3::rgb{255,0,0});
    this->ready_queue_mutex.lock();
    int size = this->ready_queue.size();
    this->ready_queue_mutex.unlock();
    return size;
}

int InnerScheduler::get_ready_queue_size_unsafe(){
    return this->ready_queue.size();
}

int InnerScheduler::get_thread_queue_size() {
  this->thread_queue_mutex.lock();
  int size = this->thread_queue.size();
  this->thread_queue_mutex.unlock();
  return size;
}

void InnerScheduler::has_update() {
  /*
std::unique_lock<std::mutex> lk(this->m);
this->update = true;
lk.unlock();
this->cv.notify_one();
*/
}

void InnerScheduler::no_update() {
  /*
std::unique_lock<std::mutex> lk(this->m);
this->update = false;
// std::cout << "WAITING ON UPDATE" << std::endl;
auto now = std::chrono::system_clock::now();
cv.wait_until(lk, now + 200us);
// cv.wait(lk);
this->update = true;
lk.unlock();
*/
}

int InnerScheduler::get_thread_queue_size_unsafe() {
  return this->thread_queue.size();
}

int InnerScheduler::get_ready_tasks_unsafe() { return this->ready_tasks; }

int InnerScheduler::get_ready_tasks() {
  my_scoped_range r("Get # Ready Tasks", nvtx3::rgb{255,0,0});
  this->ready_queue_mutex.lock();
  int size = this->ready_tasks;
  this->ready_queue_mutex.unlock();
  return size;
}

//Launch Tasks Task Callback
int InnerScheduler::run_launcher() {

  int exit_flag = 0;

  auto& msg = my_registered_string::get<launcher_msg>();
  my_scoped_range r(msg, nvtx3::rgb{127,255,0});

  if (true) {

    exit_flag = 1;
    bool has_task = true;
    int count = 0;

    while ((count < 1) && has_task) {
      has_task = this->get_ready_tasks_unsafe() > 0;

      // std::cout << "has_task: " << has_task << " " <<
      // this->get_ready_tasks_unsafe()
      //          << " " << this->ready_queue.size() << std::endl;

      count++;
      if (has_task) {

        exit_flag = 2;

        // std::cout << "Resources, VCUS" << this->get_resources_unsafe() << ",
        // "
        //<< task->vcus << std::endl;
        // this->ready_queue_mutex.lock();

        float current_resources = this->get_resources_unsafe();
        float next_resources = this->get_resources_next();
        bool has_resources = (current_resources - next_resources) >= 0;

        if (has_resources) {
          exit_flag = 3;
          bool has_thread = this->get_free_threads_unsafe() > 0;

          if (has_thread) {
            exit_flag = 4;

            InnerTask *task = this->dequeue_task();
            InnerWorker *worker = this->dequeue_worker();

            bool success = this->launch_task(task, worker);
            if (success) {
              exit_flag = 5;
            }
          } else {
            // this->enqueue_task(task);
          } // has_thread
        } else {
          // this->enqueue_task(task);
          this->no_update();
        } // has_resources
        this->no_update();
        // this->ready_queue_mutex.unlock();
      }   // if has_task
    }     // while true

    // this->launching_phase_mutex.unlock();
  }

    return exit_flag;
}

int InnerScheduler::run_scheduler() {
  // std::cout << "Running Scheduler Launcher" << std::endl;
  int exit_flag = this->run_launcher();
  // while(this->get_running_tasks() == 0 and this->get_active_tasks() > 1){
  //   launch_succeed = this->run_launcher();
  //}
  // std::cout << "Scheduler Callback Finished: " << this->active_tasks << " "
  //          << this->running_tasks << " " <<
  //          this->get_ready_queue_size_unsafe()
  //          << " " << exit_flag << std::endl;
  return exit_flag;
}

//Launch Task python callback
bool InnerScheduler::launch_task(InnerTask *task, InnerWorker *worker) {

  my_scoped_range r("launch task", nvtx3::rgb{127,127,0});
  bool success = false;
  void *py_task = task->task;
  void *py_worker = worker->worker;

  this->incr_running_tasks();
  this->decr_resources(task->vcus);

  launch_task_callback(this->call, this->func, py_task, py_worker);

  LOG("Launching Task {}", task->name);

  success = true;
  return success;
}

void InnerScheduler::run(){
  my_scoped_range r("RUN", nvtx3::rgb{127,127,0});
  unsigned long long i = 0;
  int exit_flag = 0;
  while (this->should_run) {
    exit_flag = this->run_scheduler();
    if (false) {
      std::this_thread::sleep_for(std::chrono::microseconds(20));
    }
    // std::cout << "Scheduler Loop: " << ++i << " " << exit_flag << std::endl;
    }
}

//Stop
void InnerScheduler::stop(){
    //std::cout << "Stopping Scheduler" << std::endl;
    this->should_run = false;
    launch_stop_callback(this->py_stop, this->func);
}

//Incr/Decr Counters

//running tasks
void InnerScheduler::incr_running_tasks(){
    this->running_tasks++;
}

void InnerScheduler::decr_running_tasks(){
    this->running_tasks--;
}

//active tasks
void InnerScheduler::incr_active_tasks(){
    my_scoped_range r("incr active", nvtx3::rgb{127,127,0});
    this->active_tasks_mutex.lock();
    this->active_tasks++;
    this->active_tasks_mutex.unlock();
}

bool InnerScheduler::decr_active_tasks(){
    my_scoped_range r("decr active", nvtx3::rgb{127,127,0});
    this->active_tasks_mutex.lock();
    this->active_tasks--;
    bool condition = this->active_tasks == 0;
    this->active_tasks_mutex.unlock();

    if (condition){
        this->stop();
    }

    return condition;
}

//threads
void InnerScheduler::incr_free_threads(){

    this->free_threads++;
}

void InnerScheduler::decr_free_threads(){
    this->free_threads--;
}

//resources
void InnerScheduler::incr_resources(float resources){
    ////std::cout<<"Incrementing resources: try to get lock"<< std::endl;
    //this->resources_mutex.lock();
    ////std::cout<<"Incrementing resources: got lock"<< std::endl;
    //this->resources += resources;
    this->resources.fetch_add(resources, std::memory_order_relaxed);
    this->has_update();
    //this->resources_mutex.unlock();
    ////std::cout<<"Incrementing resources: released lock"<< std::endl;

}

void InnerScheduler::incr_resources_unsafe(float resources){
    //this->resources += resources;
    this->resources.fetch_add(resources, std::memory_order_relaxed);
    this->has_update();
}

void InnerScheduler::decr_resources(float resources){
  // this->resources_mutex.lock();
  // this->resources -= resources;
  // std::cout << "Decrementing resources: " << this->resources << " "
  //          << resources << std::endl;
  this->resources.fetch_sub(resources, std::memory_order_relaxed);
  // this->resources_mutex.unlock();
}

void InnerScheduler::decr_resources_unsafe(float resources){
    //this->resources -= resources;
    this->resources.fetch_sub(resources, std::memory_order_relaxed);
}

//Get Counters
int InnerScheduler::get_running_tasks(){
    int running_tasks = this->running_tasks;
    return running_tasks;
}

int InnerScheduler::get_running_tasks_unsafe(){
    return this->running_tasks;
}

int InnerScheduler::get_active_tasks(){
    my_scoped_range r("get_active_tasks", nvtx3::rgb{127,127,0});
    this->active_tasks_mutex.lock();
    int active_tasks = this->active_tasks;
    this->active_tasks_mutex.unlock();
    return active_tasks;
}

int InnerScheduler::get_active_tasks_unsafe(){
    return this->active_tasks;
}

int InnerScheduler::get_free_threads(){
    int free_threads = this->free_threads;
    return free_threads;
}

int InnerScheduler::get_free_threads_unsafe(){
    return this->free_threads;
}

float InnerScheduler::get_resources(){
    float resources = this->resources;
    return resources;
}

float InnerScheduler::get_resources_unsafe(){
    return this->resources;
}
